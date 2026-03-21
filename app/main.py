"""OpenFish - 轻量级AI模型路由平台"""
import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import Config
from app.backends import create_backend, BaseBackend
from app.core import LoadBalancer, HealthChecker, APIKeyAuth, stats, rate_limiter
from app.api import chat_router, embeddings_router, models_router, monitor_router, config_router
from app.web import dashboard_router

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("openfish")

# 全局变量
config = Config()
backends: dict[str, BaseBackend] = {}
load_balancer = LoadBalancer()
health_checker = HealthChecker()
auth = APIKeyAuth()


async def init_backends():
    """初始化后端"""
    global backends
    backends.clear()
    # 清除旧的速率限制器
    for name in list(rate_limiter._limits.keys()):
        rate_limiter.unregister_backend(name)

    for backend_config in config.backends:
        if not backend_config.enabled:
            continue

        try:
            backend = create_backend(backend_config)
            # 设置优先级
            backend.priority = backend_config.priority
            backends[backend_config.name] = backend

            # 注册速率限制
            rate_limiter.register_backend(
                backend_config.name,
                rpm=backend_config.rate_limit.rpm,
                tpm=backend_config.rate_limit.tpm,
                concurrent=backend_config.rate_limit.concurrent
            )

            logger.info(f"Backend initialized: {backend_config.name} ({backend_config.type})")
        except Exception as e:
            logger.error(f"Failed to initialize backend {backend_config.name}: {e}")

    return backends


async def start_health_checker():
    """启动健康检查"""
    if backends:
        interval = config.routes[0].health_check_interval if config.routes else 30
        await health_checker.start(list(backends.values()), interval)


async def stop_health_checker():
    """停止健康检查"""
    await health_checker.stop()


async def close_backends():
    """关闭后端连接"""
    for backend in backends.values():
        try:
            await backend.close()
        except Exception:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("OpenFish starting...")

    # 初始化
    await init_backends()
    await start_health_checker()

    # 更新认证配置
    auth.enabled = config.auth.enabled
    auth.update_keys(config.auth.api_keys)

    logger.info(f"OpenFish started on {config.server.host}:{config.server.port}")
    logger.info(f"Backends: {list(backends.keys())}")
    logger.info(f"Dashboard: http://{config.server.host}:{config.server.port}/")

    yield

    # 清理
    logger.info("OpenFish shutting down...")
    await stop_health_checker()
    await close_backends()
    logger.info("OpenFish stopped")


# 创建FastAPI应用
app = FastAPI(
    title="OpenFish",
    description="轻量级AI模型路由平台",
    version="1.0.0",
    lifespan=lifespan
)

# CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 配置热更新中间件
@app.middleware("http")
async def config_reload_middleware(request: Request, call_next):
    """配置热更新中间件"""
    await config.check_and_reload()

    # 更新认证配置
    if auth.enabled != config.auth.enabled:
        auth.enabled = config.auth.enabled
    if auth.api_keys != set(config.auth.api_keys):
        auth.update_keys(config.auth.api_keys)

    return await call_next(request)


# API Key认证依赖
async def verify_api_key(request: Request):
    """验证API Key"""
    if not auth.verify(request):
        raise HTTPException(
            status_code=401,
            detail="Invalid API key"
        )


# 注册路由
app.include_router(dashboard_router)
app.include_router(chat_router, dependencies=[Depends(verify_api_key)])
app.include_router(embeddings_router, dependencies=[Depends(verify_api_key)])
app.include_router(models_router, dependencies=[Depends(verify_api_key)])
app.include_router(monitor_router)
app.include_router(config_router)


# 健康检查端点
@app.get("/health")
async def health():
    """健康检查"""
    return {"status": "ok", "service": "openfish"}


# 根端点
@app.get("/v1")
async def api_root():
    """API根端点"""
    return {
        "service": "OpenFish",
        "version": "1.0.0",
        "endpoints": [
            "/v1/chat/completions",
            "/v1/embeddings",
            "/v1/models",
            "/api/monitor/status"
        ]
    }


def main():
    """主入口"""
    # 从环境变量或命令行获取配置文件路径
    config_path = "config.json"
    if len(sys.argv) > 1:
        config_path = sys.argv[1]

    global config
    config = Config(config_path)

    # 设置日志级别
    log_level = config.server.log_level.lower()
    logging.getLogger().setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # 启动服务器
    uvicorn.run(
        "app.main:app",
        host=config.server.host,
        port=config.server.port,
        workers=config.server.workers,
        log_level=log_level,
        access_log=True
    )


if __name__ == "__main__":
    main()
