"""监控API端点"""
from fastapi import APIRouter, HTTPException
from app.core import stats

import logging
logger = logging.getLogger("openfish.api.monitor")

router = APIRouter()


def get_app():
    from app import main as app_main
    return app_main


@router.get("/api/monitor/status")
async def get_status():
    """获取系统状态"""
    app = get_app()
    
    backends_status = []
    for backend in app.backends.values():
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
        "stats": stats.get_summary(),
        "config": {
            "server": {
                "host": app.config.server.host,
                "port": app.config.server.port
            },
            "routes": [{"name": r.name, "strategy": r.strategy} for r in app.config.routes]
        }
    }


@router.get("/api/monitor/backends")
async def get_backends():
    """获取后端状态列表"""
    app = get_app()
    result = []
    for backend in app.backends.values():
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
    return stats.get_summary()


@router.get("/api/monitor/timeline")
async def get_timeline(minutes: int = 30):
    """获取时间线数据"""
    return stats.get_timeline(minutes)


@router.get("/api/monitor/models")
async def get_models_stats():
    """获取各模型统计"""
    result = {}
    for model in stats.model_requests.keys():
        result[model] = stats.get_model_stats(model)
    return result


@router.get("/api/monitor/health-check")
async def trigger_health_check():
    """手动触发健康检查"""
    app = get_app()
    results = {}
    for backend in app.backends.values():
        healthy = await backend.health_check()
        results[backend.name] = healthy
    return results


@router.get("/api/backends/{backend_name}/models")
async def get_backend_models(backend_name: str):
    """获取指定后端的模型列表"""
    app = get_app()
    
    if backend_name not in app.backends:
        raise HTTPException(status_code=404, detail="Backend not found")
    
    backend = app.backends[backend_name]
    try:
        models = await backend.list_models()
        return {
            "backend": backend_name,
            "models": models
        }
    except Exception as e:
        logger.error(f"Failed to get models from {backend_name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/backends/{backend_name}/models/{model_id}")
async def get_backend_model_detail(backend_name: str, model_id: str):
    """获取指定后端的模型详情"""
    app = get_app()
    
    if backend_name not in app.backends:
        raise HTTPException(status_code=404, detail="Backend not found")
    
    backend = app.backends[backend_name]
    try:
        models = await backend.list_models()
        for m in models:
            if m.get("id") == model_id:
                return m
        raise HTTPException(status_code=404, detail="Model not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get model detail from {backend_name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
