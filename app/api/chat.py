"""Chat Completions API端点"""
import time
import json
from typing import Dict, List, Any, Optional, Tuple
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from app.core import stats, rate_limiter

import logging
logger = logging.getLogger("openfish.api.chat")

router = APIRouter()


def get_app():
    from app import main as app_main
    return app_main


def parse_model_field(model: str, config) -> Tuple[str, Optional[object]]:
    """
    解析model字段
    返回: (实际model_id, 路由配置)
    
    格式:
    - "gpt-4" -> 直接使用模型，失败后用默认路由回退
    - "back-default" -> 使用名为default的路由配置
    - "back-openai" -> 使用名为openai的路由配置
    """
    if model.startswith("back-"):
        # 使用指定路由
        route_name = model[5:]  # 去掉 "back-" 前缀
        for route in config.routes:
            if route.name == route_name:
                return "*", route  # 返回通配符，让路由决定使用哪些后端
        # 路由不存在，返回默认
        return "*", config.routes[0] if config.routes else None
    else:
        # 直接使用模型名
        return model, config.routes[0] if config.routes else None


def find_backends_for_model(model_id: str, config, backends: dict) -> List:
    """查找支持指定模型的后端"""
    if model_id == "*":
        # 返回所有启用的后端
        return [b for b in backends.values() if b.status.healthy]
    
    available = []
    for backend in backends.values():
        if not backend.status.healthy:
            continue
        backend_config = config.get_backend_by_name(backend.name)
        if backend_config:
            for m in backend_config.models:
                if m.id == "*" or m.id == model_id:
                    if m.enabled:
                        available.append(backend)
                        break
    return available


def extract_request_params(body: Dict) -> Dict[str, Any]:
    """提取请求参数（支持tools等所有OpenAI参数）"""
    params = {}
    
    for key in ["temperature", "max_tokens", "top_p", "frequency_penalty", 
                "presence_penalty", "stop", "n", "seed", "response_format",
                "tools", "tool_choice", "functions", "function_call",
                "logprobs", "top_logprobs"]:
        if key in body and body[key] is not None:
            params[key] = body[key]
    
    return params


@router.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """OpenAI兼容的chat/completions端点"""
    app = get_app()

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    raw_model = body.get("model", "")
    messages = body.get("messages", [])
    stream = body.get("stream", False)

    if not raw_model:
        raise HTTPException(status_code=400, detail="Model is required")
    if not messages:
        raise HTTPException(status_code=400, detail="Messages are required")

    # 解析model字段
    model_id, route = parse_model_field(raw_model, app.config)

    # 查找可用后端
    if model_id == "*" and route:
        # 使用路由配置的模型列表
        available_backends = []
        for backend_name in route.fallback_order if route.fallback_order else [b.name for b in app.config.backends if b.enabled]:
            if backend_name in app.backends and app.backends[backend_name].status.healthy:
                available_backends.append(app.backends[backend_name])
        # 如果路由没有配置fallback_order，使用所有健康的后端
        if not available_backends:
            available_backends = [b for b in app.backends.values() if b.status.healthy]
    else:
        available_backends = find_backends_for_model(model_id, app.config, app.backends)

    if not available_backends:
        raise HTTPException(
            status_code=503,
            detail=f"No healthy backend available for model: {raw_model}"
        )

    # 获取路由配置
    strategy = route.strategy if route else "latency"
    fallback_order = route.fallback_order if route else []
    fallback_rules = route.fallback_rules if route else []

    # 估算tokens
    estimated_tokens = sum(len(str(m.get("content", ""))) for m in messages) // 4

    # 选择后端
    selected_backend = None
    tried_backends = []

    for backend in available_backends:
        if backend in tried_backends:
            continue
        if not await rate_limiter.can_request(backend.name, estimated_tokens):
            tried_backends.append(backend)
            continue
        if rate_limiter.is_near_limit(backend.name, threshold=0.8):
            tried_backends.append(backend)
            continue
        selected_backend = backend
        break

    # 回退规则
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

    # 回退顺序
    if not selected_backend and fallback_order:
        for name in fallback_order:
            if name in app.backends:
                backend = app.backends[name]
                if backend.status.healthy and await rate_limiter.can_request(backend.name, estimated_tokens):
                    selected_backend = backend
                    break

    # 最后选择
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
    if backend_config and model_id != "*":
        for m in backend_config.models:
            if m.id == model_id:
                actual_model = m.name
                break
    elif backend_config and model_id == "*":
        # 使用路由时，选择第一个启用的模型
        for m in backend_config.models:
            if m.enabled:
                actual_model = m.name
                break

    # 提取请求参数
    request_params = extract_request_params(body)

    # 获取速率限制许可
    await rate_limiter.acquire(selected_backend.name, estimated_tokens)

    start_time = time.time()

    try:
        if stream:
            return StreamingResponse(
                stream_chat_completion(selected_backend, actual_model, messages, request_params, start_time),
                media_type="text/event-stream"
            )
        else:
            result = await selected_backend.chat_completion(
                model=actual_model,
                messages=messages,
                stream=False,
                **request_params
            )

            latency = time.time() - start_time
            tokens = result.get("usage", {}).get("total_tokens", 0)
            await stats.record(raw_model, selected_backend.name, tokens, latency, True)

            return result

    except Exception as e:
        latency = time.time() - start_time
        await stats.record(raw_model, selected_backend.name, 0, latency, False)
        logger.error(f"Chat completion error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        rate_limiter.release(selected_backend.name)


async def stream_chat_completion(backend, model: str, messages: List[Dict], params: Dict, start_time: float):
    """流式响应"""
    try:
        async for chunk in backend.chat_completion_stream(
            model=model,
            messages=messages,
            **params
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
