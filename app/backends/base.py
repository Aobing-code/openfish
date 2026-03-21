"""后端适配器基类"""
import asyncio
import time
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Dict, List, Optional
from dataclasses import dataclass
import logging

logger = logging.getLogger("openfish.backends")


@dataclass
class BackendStatus:
    """后端状态"""
    name: str
    healthy: bool = True
    latency: float = 0.0
    last_check: float = 0
    error_count: int = 0
    total_requests: int = 0
    total_tokens: int = 0


class BaseBackend(ABC):
    """后端基类"""

    def __init__(self, name: str, url: str, **kwargs):
        self.name = name
        self.url = url.rstrip("/")
        self.api_key = kwargs.get("api_key")
        self.api_keys = kwargs.get("api_keys", []) or ([self.api_key] if self.api_key else [])
        self._current_key_index = 0
        self.weight = kwargs.get("weight", 1)
        self.timeout = kwargs.get("timeout", 60)
        self.verify_ssl = kwargs.get("verify_ssl", True)
        self.models = kwargs.get("models", [])
        self.priority = kwargs.get("priority", 1)
        self.status = BackendStatus(name=name)

    def get_next_api_key(self) -> Optional[str]:
        """轮询获取下一个API Key"""
        if not self.api_keys:
            return None
        key = self.api_keys[self._current_key_index % len(self.api_keys)]
        self._current_key_index = (self._current_key_index + 1) % len(self.api_keys)
        return key

    @abstractmethod
    async def chat_completion(
        self,
        model: str,
        messages: List[Dict[str, str]],
        stream: bool = False,
        **kwargs
    ) -> Any:
        """聊天补全"""
        pass

    @abstractmethod
    def chat_completion_stream(
        self,
        model: str,
        messages: List[Dict[str, str]],
        **kwargs
    ) -> AsyncIterator[Dict[str, Any]]:
        """流式聊天补全"""
        pass

    @abstractmethod
    async def embedding(
        self,
        model: str,
        input_text: str | List[str],
        **kwargs
    ) -> Any:
        """向量嵌入"""
        pass

    @abstractmethod
    async def list_models(self) -> List[str]:
        """列出可用模型"""
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """健康检查"""
        pass

    def update_status(self, healthy: bool, latency: float = 0) -> None:
        """更新状态"""
        self.status.healthy = healthy
        self.status.latency = latency
        self.status.last_check = time.time()
        if not healthy:
            self.status.error_count += 1
        else:
            self.status.error_count = 0

    def record_request(self, tokens: int = 0) -> None:
        """记录请求"""
        self.status.total_requests += 1
        self.status.total_tokens += tokens
