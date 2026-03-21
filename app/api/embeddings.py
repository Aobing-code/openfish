"""Embeddings API端点"""
import time
from fastapi import APIRouter, HTTPException, Request
from app.core import stats

import logging
logger = logging.getLogger("openfish.api.embeddings")

router = APIRouter()


def get_app():
    from app import main as app_main
    return app_main


@router.post("/v1/embeddings")
async def create_embeddings(request: Request):
    """OpenAI兼容的embeddings端点"""
    app = get_app()

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    model = body.get("model", "")
    input_text = body.get("input", "")

    if not model:
        raise HTTPException(status_code=400, detail="Model is required")
    if not input_text:
        raise HTTPException(status_code=400, detail="Input is required")

    # 获取支持该模型的后端
    available_backends = []
    for backend in app.backends.values():
        if not backend.status.healthy:
            continue
        if "*" in backend.models or model in backend.models:
            available_backends.append(backend)

    if not available_backends:
        raise HTTPException(
            status_code=503,
            detail=f"No healthy backend available for model: {model}"
        )

    # 获取路由配置
    route = app.config.routes[0] if app.config.routes else None
    strategy = route.strategy if route else "latency"
    fallback_order = route.fallback_order if route else []

    # 选择后端
    backend = app.load_balancer.select(
        available_backends,
        strategy,
        fallback_order=fallback_order,
        backends_map=app.backends
    )
    if not backend:
        raise HTTPException(status_code=503, detail="No backend available")

    start_time = time.time()

    try:
        result = await backend.embedding(
            model=model,
            input_text=input_text
        )

        latency = time.time() - start_time
        tokens = result.get("usage", {}).get("total_tokens", 0)
        await stats.record(model, backend.name, tokens, latency, True)

        return result

    except Exception as e:
        latency = time.time() - start_time
        await stats.record(model, backend.name, 0, latency, False)
        logger.error(f"Embedding error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
