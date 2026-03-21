"""监控API端点"""
from typing import Dict, Any, List
from fastapi import APIRouter

import logging
logger = logging.getLogger("openfish.api.monitor")

router = APIRouter()

# 将在main.py中注入
backends_manager = None
stats_collector = None
config = None


@router.get("/api/monitor/status")
async def get_status():
    """获取系统状态"""
    backends_status = []
    for backend in backends_manager.values():
        backends_status.append({
            "name": backend.name,
            "type": backend.__class__.__name__.replace("Backend", "").lower(),
            "url": backend.url,
            "healthy": backend.status.healthy,
            "latency": backend.status.latency,
            "last_check": backend.status.last_check,
            "error_count": backend.status.error_count,
            "total_requests": backend.status.total_requests,
            "total_tokens": backend.status.total_tokens,
            "models": backend.models
        })

    return {
        "backends": backends_status,
        "stats": stats_collector.get_summary(),
        "config": {
            "server": {
                "host": config.server.host,
                "port": config.server.port
            },
            "routes": [{"name": r.name, "strategy": r.strategy} for r in config.routes]
        }
    }


@router.get("/api/monitor/backends")
async def get_backends():
    """获取后端状态列表"""
    result = []
    for backend in backends_manager.values():
        result.append({
            "name": backend.name,
            "type": backend.__class__.__name__.replace("Backend", "").lower(),
            "url": backend.url,
            "healthy": backend.status.healthy,
            "latency": backend.status.latency,
            "last_check": backend.status.last_check,
            "error_count": backend.status.error_count,
            "total_requests": backend.status.total_requests,
            "total_tokens": backend.status.total_tokens,
            "models": backend.models
        })
    return result


@router.get("/api/monitor/stats")
async def get_stats():
    """获取统计信息"""
    return stats_collector.get_summary()


@router.get("/api/monitor/timeline")
async def get_timeline(minutes: int = 30):
    """获取时间线数据"""
    return stats_collector.get_timeline(minutes)


@router.get("/api/monitor/models")
async def get_models_stats():
    """获取各模型统计"""
    result = {}
    for model in stats_collector.model_requests.keys():
        result[model] = stats_collector.get_model_stats(model)
    return result


@router.post("/api/monitor/health-check")
async def trigger_health_check():
    """手动触发健康检查"""
    results = {}
    for backend in backends_manager.values():
        healthy = await backend.health_check()
        results[backend.name] = healthy
    return results
