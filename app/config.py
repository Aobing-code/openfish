"""配置管理模块 - 支持热更新"""
import json
import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
import logging

logger = logging.getLogger("openfish.config")


@dataclass
class RateLimit:
    """速率限制配置"""
    rpm: int = 0  # 每分钟请求数，0表示不限制
    tpm: int = 0  # 每分钟token数，0表示不限制
    concurrent: int = 0  # 并发数，0表示不限制


@dataclass
class ModelConfig:
    """模型配置"""
    id: str  # 模型ID，用于请求时选择
    name: str  # 实际模型名称
    context_length: int = 4096  # 上下文长度
    enabled: bool = True
    rate_limit: RateLimit = field(default_factory=RateLimit)  # 模型独立速率限制


@dataclass
class BackendConfig:
    """后端配置"""
    name: str
    type: str  # ollama, openai, anthropic, google
    url: str
    api_keys: List[str] = field(default_factory=list)  # 支持多个API Key
    weight: int = 1
    enabled: bool = True
    timeout: int = 60
    verify_ssl: bool = True
    models: List[ModelConfig] = field(default_factory=list)
    rate_limit: RateLimit = field(default_factory=RateLimit)
    priority: int = 1  # 优先级，数字越小优先级越高


@dataclass
class FallbackRule:
    """回退规则"""
    name: str
    condition: str = "error"  # error, timeout, rate_limit, latency
    threshold: float = 0  # 阈值（延迟秒数或错误次数）
    backends: List[str] = field(default_factory=list)  # 回退后端名称列表


@dataclass
class RouteConfig:
    """路由配置"""
    name: str
    models: List[str] = field(default_factory=lambda: ["*"])  # 支持的模型ID
    strategy: str = "latency"  # round_robin, latency, random, weighted, priority, custom
    failover: bool = True
    health_check_interval: int = 30
    fallback_order: List[str] = field(default_factory=list)
    fallback_rules: List[FallbackRule] = field(default_factory=list)


@dataclass
class ServerConfig:
    """服务器配置"""
    host: str = "0.0.0.0"
    port: int = 8080
    workers: int = 1
    log_level: str = "info"


@dataclass
class AuthConfig:
    """认证配置"""
    enabled: bool = True
    api_keys: List[str] = field(default_factory=lambda: ["sk-openfish"])


class Config:
    """配置管理器 - 支持热更新"""

    def __init__(self, config_path: str = "config.json"):
        self.config_path = Path(config_path)
        self._last_modified: float = 0
        self._config: Dict[str, Any] = {}
        self._lock = asyncio.Lock()

        self.server = ServerConfig()
        self.backends: List[BackendConfig] = []
        self.routes: List[RouteConfig] = []
        self.auth = AuthConfig()

        self.load()

    def load(self) -> None:
        """加载配置文件"""
        if not self.config_path.exists():
            logger.warning(f"Config file not found: {self.config_path}, using defaults")
            self._create_default_config()
            return

        try:
            mtime = self.config_path.stat().st_mtime
            if mtime == self._last_modified:
                return

            with open(self.config_path, "r", encoding="utf-8") as f:
                self._config = json.load(f)

            self._last_modified = mtime
            self._parse_config()
            logger.info(f"Config loaded from {self.config_path}")

        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            if not self._config:
                self._create_default_config()

    def _parse_config(self) -> None:
        """解析配置"""
        # 服务器配置
        server = self._config.get("server", {})
        self.server = ServerConfig(
            host=server.get("host", "0.0.0.0"),
            port=server.get("port", 8080),
            workers=server.get("workers", 1),
            log_level=server.get("log_level", "info")
        )

        # 后端配置
        self.backends = []
        for b in self._config.get("backends", []):
            # 解析速率限制
            rl = b.get("rate_limit", {})
            rate_limit = RateLimit(
                rpm=rl.get("rpm", 0),
                tpm=rl.get("tpm", 0),
                concurrent=rl.get("concurrent", 0)
            )

            # 解析模型列表
            models = []
            for m in b.get("models", []):
                if isinstance(m, str):
                    # 兼容旧格式
                    models.append(ModelConfig(id=m, name=m))
                else:
                    # 解析模型独立速率限制
                    m_rl = m.get("rate_limit", {})
                    model_rate_limit = RateLimit(
                        rpm=m_rl.get("rpm", 0),
                        tpm=m_rl.get("tpm", 0),
                        concurrent=m_rl.get("concurrent", 0)
                    )
                    models.append(ModelConfig(
                        id=m.get("id", ""),
                        name=m.get("name", m.get("id", "")),
                        context_length=m.get("context_length", 4096),
                        enabled=m.get("enabled", True),
                        rate_limit=model_rate_limit
                    ))

            # 兼容旧的api_key格式
            api_keys = b.get("api_keys", [])
            if not api_keys and b.get("api_key"):
                api_keys = [b["api_key"]]

            self.backends.append(BackendConfig(
                name=b.get("name", ""),
                type=b.get("type", "custom"),
                url=b.get("url", ""),
                api_keys=api_keys,
                weight=b.get("weight", 1),
                enabled=b.get("enabled", True),
                timeout=b.get("timeout", 60),
                verify_ssl=b.get("verify_ssl", True),
                models=models,
                rate_limit=rate_limit,
                priority=b.get("priority", 1)
            ))

        # 路由配置
        self.routes = []
        for r in self._config.get("routes", []):
            # 解析回退规则
            fallback_rules = []
            for fr in r.get("fallback_rules", []):
                fallback_rules.append(FallbackRule(
                    name=fr.get("name", ""),
                    condition=fr.get("condition", "error"),
                    threshold=fr.get("threshold", 0),
                    backends=fr.get("backends", [])
                ))

            self.routes.append(RouteConfig(
                name=r.get("name", ""),
                models=r.get("models", ["*"]),
                strategy=r.get("strategy", "latency"),
                failover=r.get("failover", True),
                health_check_interval=r.get("health_check_interval", 30),
                fallback_order=r.get("fallback_order", []),
                fallback_rules=fallback_rules
            ))

        # 认证配置
        auth = self._config.get("auth", {})
        self.auth = AuthConfig(
            enabled=auth.get("enabled", True),
            api_keys=auth.get("api_keys", ["sk-openfish"])
        )

    def _create_default_config(self) -> None:
        """创建默认配置"""
        self._config = {
            "server": {
                "host": "0.0.0.0",
                "port": 8080,
                "workers": 1,
                "log_level": "info"
            },
            "backends": [
                {
                    "name": "ollama-local",
                    "type": "ollama",
                    "url": "http://localhost:11434",
                    "api_keys": [],
                    "weight": 10,
                    "enabled": True,
                    "timeout": 120,
                    "verify_ssl": False,
                    "models": [
                        {"id": "llama3", "name": "llama3", "context_length": 8192},
                        {"id": "qwen2", "name": "qwen2", "context_length": 32768}
                    ],
                    "rate_limit": {"rpm": 0, "tpm": 0, "concurrent": 10},
                    "priority": 1
                }
            ],
            "routes": [
                {
                    "name": "default",
                    "models": ["*"],
                    "strategy": "latency",
                    "failover": True,
                    "health_check_interval": 30,
                    "fallback_order": [],
                    "fallback_rules": [
                        {
                            "name": "rate-limit-fallback",
                            "condition": "rate_limit",
                            "threshold": 0,
                            "backends": []
                        },
                        {
                            "name": "error-fallback",
                            "condition": "error",
                            "threshold": 3,
                            "backends": []
                        },
                        {
                            "name": "latency-fallback",
                            "condition": "latency",
                            "threshold": 10.0,
                            "backends": []
                        }
                    ]
                }
            ],
            "auth": {
                "enabled": False,
                "api_keys": ["sk-openfish"]
            }
        }
        self._parse_config()

    async def check_and_reload(self) -> bool:
        """检查并热重载配置"""
        async with self._lock:
            try:
                if not self.config_path.exists():
                    return False

                mtime = self.config_path.stat().st_mtime
                if mtime > self._last_modified:
                    self.load()
                    return True
            except Exception as e:
                logger.error(f"Config reload failed: {e}")
            return False

    def get_backend_by_name(self, name: str) -> Optional[BackendConfig]:
        """根据名称获取后端"""
        for b in self.backends:
            if b.name == name:
                return b
        return None

    def get_backends_for_model(self, model_id: str) -> List[BackendConfig]:
        """获取支持指定模型ID的后端列表"""
        result = []
        for b in self.backends:
            if not b.enabled:
                continue
            for m in b.models:
                if m.id == "*" or m.id == model_id:
                    if m.enabled:
                        result.append(b)
                        break
        return result

    def find_model_config(self, backend: BackendConfig, model_id: str) -> Optional[ModelConfig]:
        """查找后端中的模型配置"""
        for m in backend.models:
            if m.id == model_id or m.id == "*":
                return m
        return None

    def save(self) -> None:
        """保存配置到文件"""
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self._config, f, indent=2, ensure_ascii=False)
            logger.info(f"Config saved to {self.config_path}")
        except Exception as e:
            logger.error(f"Failed to save config: {e}")


# 全局配置实例
config = Config()
