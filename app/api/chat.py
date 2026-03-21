"""Chat Completions API端点"""
import time
import json
from typing import Dict, List
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from app.core import stats, rate_limiter

import logging
logger = logging.getLogger("openfish.api.chat")

router = APIRouter()


def get_app():
    from app import main as app_main
    return app_main


@router.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """OpenAI兼容的chat/completions端点"""
    app = get_app()

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    model_id = body.get("model", "")
    messages = body.get("messages", [])
    stream = body.get("stream", False)

    if not model_id:
        raise HTTPException(status_code=400, detail="Model is required")
    if not messages:
        raise HTTPException(status_code=400, detail="Messages are required")

    # 获取支持该模型ID的后端
    available_backends = []
    for backend in app.backends.values():
        if not backend.status.healthy:
            continue
        # 检查后端是否支持该模型ID
        for m in app.config.get_backend_by_name(backend.name).models if app.config.get_backend_by_name(backend.name) else []:
            if m.id == "*" or m.id == model_id:
                if m.enabled:
                    available_backends.append(backend)
                    break

    if not available_backends:
        raise HTTPException(
            status_code=503,
            detail=f"No healthy backend available for model: {model_id}"
        )

    # 获取路由配置
    route = app.config.routes[0] if app.config.routes else None
    strategy = route.strategy if route else "latency"
    fallback_order = route.fallback_order if route else []
    fallback_rules = route.fallback_rules if route else []

    # 估算tokens（简单估算）
    estimated_tokens = sum(len(m.get("content", "")) for m in messages) // 4

    # 选择后端（带速率限制检查和故障预判）
    selected_backend = None
    tried_backends = []

    # 首先尝试主选择策略
    for backend in available_backends:
        if backend in tried_backends:
            continue

        # 检查速率限制
        if not await rate_limiter.can_request(backend.name, estimated_tokens):
            logger.debug(f"Backend {backend.name} rate limited, trying next")
            tried_backends.append(backend)
            continue

        # 检查是否接近限制（故障预判）
        if rate_limiter.is_near_limit(backend.name, threshold=0.8):
            logger.debug(f"Backend {backend.name} near rate limit, considering fallback")
            # 不立即跳过，但降低优先级
            tried_backends.append(backend)
            continue

        selected_backend = backend
        break

    # 如果主选择失败，尝试回退规则
    if not selected_backend and fallback_rules:
        for rule in fallback_rules:
            if rule.condition in ["rate_limit", "error"]:
                for backend_name in rule.backends:
                    if backend_name in app.backends:
                        backend = app.backends[backend_name]
                        if backend.status.healthy and await rate_limiter.can_request(backend.name, estimated_tokens):
                            selected_backend = backend
                            break
            if selected_backend:
                break

    # 最后尝试回退顺序
    if not selected_backend and fallback_order:
        for name in fallback_order:
            if name in app.backends:
                backend = app.backends[name]
                if backend.status.healthy and await rate_limiter.can_request(backend.name, estimated_tokens):
                    selected_backend = backend
                    break

    # 如果还是没有，选择第一个可用的
    if not selected_backend:
        for backend in available_backends:
            if backend not in tried_backends:
                selected_backend = backend
                break

    if not selected_backend:
        raise HTTPException(status_code=503, detail="All backends are rate limited or unavailable")

    # 获取实际模型名称
    backend_config = app.config.get_backend_by_name(selected_backend.name)
    actual_model = model_id
    if backend_config:
        for m in backend_config.models:
            if m.id == model_id:
                actual_model = m.name
                break

    # 获取速率限制许可
    await rate_limiter.acquire(selected_backend.name, estimated_tokens)

    start_time = time.time()

    try:
        if stream:
            return StreamingResponse(
                stream_chat_completion(selected_backend, actual_model, messages, body, start_time),
                media_type="text/event-stream"
            )
        else:
            result = await selected_backend.chat_completion(
                model=actual_model,
                messages=messages,
                stream=False,
                temperature=body.get("temperature"),
                max_tokens=body.get("max_tokens"),
                top_p=body.get("top_p")
            )

            latency = time.time() - start_time
            tokens = result.get("usage", {}).get("total_tokens", 0)
            await stats.record(model_id, selected_backend.name, tokens, latency, True)

            return result

    except Exception as e:
        latency = time.time() - start_time
        await stats.record(model_id, selected_backend.name, 0, latency, False)
        logger.error(f"Chat completion error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        rate_limiter.release(selected_backend.name)


async def stream_chat_completion(backend, model: str, messages: List[Dict], body: Dict, start_time: float):
    """流式响应"""
    try:
        async for chunk in backend.chat_completion_stream(
            model=model,
            messages=messages,
            temperature=body.get("temperature"),
            max_tokens=body.get("max_tokens"),
            top_p=body.get("top_p")
        ):
            yield f"data: {json.dumps(chunk)}\n\n"

        yield "data: [DONE]\n\n"

        latency = time.time() - start_time
        await stats.record(model, backend.name, 0, latency, True)

    except Exception as e:
        latency = time.time() - start_time
        await stats.record(model, backend.name, 0, latency, False)
        logger.error(f"Stream error: {e}")
        error_chunk = {"error": {"message": str(e), "type": "server_error"}}
        yield f"data: {json.dumps(error_chunk)}\n\n"
    finally:
        rate_limiter.release(backend.name)
