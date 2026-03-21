"""配置管理API端点"""
import asyncio
from typing import Dict, Any, List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import logging
logger = logging.getLogger("openfish.api.config")

router = APIRouter()


class RateLimitCreate(BaseModel):
    rpm: int = 0
    tpm: int = 0
    concurrent: int = 0


class ModelCreate(BaseModel):
    id: str
    name: str
    context_length: int = 4096
    enabled: bool = True
    rate_limit: RateLimitCreate = RateLimitCreate()


class BackendCreate(BaseModel):
    name: str
    type: str  # ollama, openai, anthropic, google
    url: str
    api_keys: List[str] = []
    weight: int = 1
    enabled: bool = True
    timeout: int = 60
    verify_ssl: bool = True
    models: List[ModelCreate] = []
    rate_limit: RateLimitCreate = RateLimitCreate()
    priority: int = 1


class FallbackRuleCreate(BaseModel):
    name: str
    condition: str = "error"  # error, timeout, rate_limit, latency
    threshold: float = 0
    backends: List[str] = []


class RouteCreate(BaseModel):
    name: str
    models: List[str] = ["*"]
    strategy: str = "latency"
    failover: bool = True
    health_check_interval: int = 30
    fallback_order: List[str] = []
    fallback_rules: List[FallbackRuleCreate] = []


class AuthUpdate(BaseModel):
    enabled: bool = True
    api_keys: List[str] = []


class ServerUpdate(BaseModel):
    host: str | None = None
    port: int | None = None
    log_level: str | None = None


class FallbackOrderUpdate(BaseModel):
    fallback_order: List[str]


def get_app():
    from app import main as app_main
    return app_main


@router.get("/api/config")
async def get_config():
    """获取当前配置"""
    app = get_app()
    config = app.config

    def model_to_dict(m):
        return {
            "id": m.id,
            "name": m.name,
            "context_length": m.context_length,
            "enabled": m.enabled,
            "rate_limit": {
                "rpm": m.rate_limit.rpm,
                "tpm": m.rate_limit.tpm,
                "concurrent": m.rate_limit.concurrent
            }
        }

    def backend_to_dict(b):
        return {
            "name": b.name,
            "type": b.type,
            "url": b.url,
            "api_keys": b.api_keys,
            "weight": b.weight,
            "enabled": b.enabled,
            "timeout": b.timeout,
            "verify_ssl": b.verify_ssl,
            "models": [model_to_dict(m) for m in b.models],
            "rate_limit": {
                "rpm": b.rate_limit.rpm,
                "tpm": b.rate_limit.tpm,
                "concurrent": b.rate_limit.concurrent
            },
            "priority": b.priority
        }

    def route_to_dict(r):
        return {
            "name": r.name,
            "models": r.models,
            "strategy": r.strategy,
            "failover": r.failover,
            "health_check_interval": r.health_check_interval,
            "fallback_order": r.fallback_order,
            "fallback_rules": [
                {
                    "name": fr.name,
                    "condition": fr.condition,
                    "threshold": fr.threshold,
                    "backends": fr.backends
                }
                for fr in r.fallback_rules
            ]
        }

    return {
        "server": {
            "host": config.server.host,
            "port": config.server.port,
            "log_level": config.server.log_level
        },
        "backends": [backend_to_dict(b) for b in config.backends],
        "routes": [route_to_dict(r) for r in config.routes],
        "auth": {
            "enabled": config.auth.enabled,
            "api_keys": config.auth.api_keys
        }
    }


@router.put("/api/config/server")
async def update_server(body: ServerUpdate):
    """更新服务器配置"""
    app = get_app()
    config = app.config

    data = config._config.get("server", {})
    if body.host is not None:
        data["host"] = body.host
    if body.port is not None:
        data["port"] = body.port
    if body.log_level is not None:
        data["log_level"] = body.log_level
    config._config["server"] = data
    config.save()
    config.load()
    return {"status": "ok"}


@router.post("/api/config/backends")
async def add_backend(body: BackendCreate):
    """添加后端"""
    app = get_app()
    config = app.config

    for b in config._config.get("backends", []):
        if b["name"] == body.name:
            raise HTTPException(status_code=400, detail="Backend name already exists")

    backend_data = {
        "name": body.name,
        "type": body.type,
        "url": body.url,
        "api_keys": body.api_keys,
        "weight": body.weight,
        "enabled": body.enabled,
        "timeout": body.timeout,
        "verify_ssl": body.verify_ssl,
        "models": [{"id": m.id, "name": m.name, "context_length": m.context_length, "enabled": m.enabled, "rate_limit": {"rpm": m.rate_limit.rpm, "tpm": m.rate_limit.tpm, "concurrent": m.rate_limit.concurrent}} for m in body.models],
        "rate_limit": {"rpm": body.rate_limit.rpm, "tpm": body.rate_limit.tpm, "concurrent": body.rate_limit.concurrent},
        "priority": body.priority
    }

    if "backends" not in config._config:
        config._config["backends"] = []
    config._config["backends"].append(backend_data)
    config.save()
    config.load()
    await app.init_backends()

    return {"status": "ok", "backend": backend_data}


@router.put("/api/config/backends/{name}")
async def update_backend(name: str, body: BackendCreate):
    """更新后端"""
    app = get_app()
    config = app.config

    backends = config._config.get("backends", [])
    for i, b in enumerate(backends):
        if b["name"] == name:
            backends[i] = {
                "name": body.name,
                "type": body.type,
                "url": body.url,
                "api_keys": body.api_keys,
                "weight": body.weight,
                "enabled": body.enabled,
                "timeout": body.timeout,
                "verify_ssl": body.verify_ssl,
                "models": [{"id": m.id, "name": m.name, "context_length": m.context_length, "enabled": m.enabled, "rate_limit": {"rpm": m.rate_limit.rpm, "tpm": m.rate_limit.tpm, "concurrent": m.rate_limit.concurrent}} for m in body.models],
                "rate_limit": {"rpm": body.rate_limit.rpm, "tpm": body.rate_limit.tpm, "concurrent": body.rate_limit.concurrent},
                "priority": body.priority
            }
            config.save()
            config.load()
            await app.init_backends()
            return {"status": "ok"}

    raise HTTPException(status_code=404, detail="Backend not found")


@router.delete("/api/config/backends/{name}")
async def delete_backend(name: str):
    """删除后端"""
    app = get_app()
    config = app.config

    backends = config._config.get("backends", [])
    config._config["backends"] = [b for b in backends if b["name"] != name]
    config.save()
    config.load()
    await app.init_backends()
    return {"status": "ok"}


@router.put("/api/config/backends/{name}/toggle")
async def toggle_backend(name: str):
    """启用/禁用后端"""
    app = get_app()
    config = app.config

    backends = config._config.get("backends", [])
    for b in backends:
        if b["name"] == name:
            b["enabled"] = not b.get("enabled", True)
            config.save()
            config.load()
            await app.init_backends()
            return {"status": "ok", "enabled": b["enabled"]}

    raise HTTPException(status_code=404, detail="Backend not found")


@router.post("/api/config/routes")
async def add_route(body: RouteCreate):
    """添加路由"""
    app = get_app()
    config = app.config

    for r in config._config.get("routes", []):
        if r["name"] == body.name:
            raise HTTPException(status_code=400, detail="Route name already exists")

    route_data = {
        "name": body.name,
        "models": body.models,
        "strategy": body.strategy,
        "failover": body.failover,
        "health_check_interval": body.health_check_interval,
        "fallback_order": body.fallback_order,
        "fallback_rules": [{"name": fr.name, "condition": fr.condition, "threshold": fr.threshold, "backends": fr.backends} for fr in body.fallback_rules]
    }

    if "routes" not in config._config:
        config._config["routes"] = []
    config._config["routes"].append(route_data)
    config.save()
    config.load()

    return {"status": "ok", "route": route_data}


@router.put("/api/config/routes/{name}")
async def update_route(name: str, body: RouteCreate):
    """更新路由"""
    app = get_app()
    config = app.config

    routes = config._config.get("routes", [])
    for i, r in enumerate(routes):
        if r["name"] == name:
            routes[i] = {
                "name": body.name,
                "models": body.models,
                "strategy": body.strategy,
                "failover": body.failover,
                "health_check_interval": body.health_check_interval,
                "fallback_order": body.fallback_order,
                "fallback_rules": [{"name": fr.name, "condition": fr.condition, "threshold": fr.threshold, "backends": fr.backends} for fr in body.fallback_rules]
            }
            config.save()
            config.load()
            return {"status": "ok"}

    raise HTTPException(status_code=404, detail="Route not found")


@router.delete("/api/config/routes/{name}")
async def delete_route(name: str):
    """删除路由"""
    app = get_app()
    config = app.config

    routes = config._config.get("routes", [])
    config._config["routes"] = [r for r in routes if r["name"] != name]
    config.save()
    config.load()
    return {"status": "ok"}


@router.put("/api/config/routes/{name}/fallback-order")
async def update_fallback_order(name: str, body: FallbackOrderUpdate):
    """更新路由回退顺序"""
    app = get_app()
    config = app.config

    routes = config._config.get("routes", [])
    for r in routes:
        if r["name"] == name:
            r["fallback_order"] = body.fallback_order
            config.save()
            config.load()
            return {"status": "ok", "fallback_order": body.fallback_order}

    raise HTTPException(status_code=404, detail="Route not found")


@router.put("/api/config/auth")
async def update_auth(body: AuthUpdate):
    """更新认证配置"""
    app = get_app()
    config = app.config

    config._config["auth"] = {
        "enabled": body.enabled,
        "api_keys": body.api_keys
    }
    config.save()
    config.load()
    return {"status": "ok"}
