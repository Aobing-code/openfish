"""Chat Completions API端点"""
import time
import json
from typing import Dict, List, Any, Optional, Tuple
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from app.core import stats, rate_limiter
from app.core.balancer import HealthChecker

import logging
logger = logging.getLogger("openfish.api.chat")

router = APIRouter()

# 全局健康检查器引用
_health_checker: Optional[HealthChecker] = None


def get_app():
    from app import main as app_main
    return app_main


def get_health_checker() -> HealthChecker:
    global _health_checker
    if _health_checker is None:
        from app.main import health_checker
        _health_checker = health_checker
    return _health_checker


def estimate_tokens(messages: List[Dict]) -> int:
    """估算消息的token数量"""
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, list):
            for part in content:
                if part.get("type") == "text":
                    total += len(part.get("text", "")) // 4
                elif part.get("type") in ["image_url", "image_base64"]:
                    total += 1000
        else:
            total += len(str(content)) // 4
    return total


def parse_fallback_target(target: str) -> Tuple[str, Optional[str]]:
    """解析回退目标: provider/model 或 provider"""
    if "/" in target:
        parts = target.split("/", 1)
        return parts[0], parts[1]
    return target, None


def extract_request_params(body: Dict) -> Dict[str, Any]:
    """提取请求参数"""
    params = {}
    for key in ["temperature", "max_tokens", "top_p", "frequency_penalty", 
                "presence_penalty", "stop", "n", "seed", "response_format",
                "tools", "tool_choice", "functions", "function_call",
                "logprobs", "top_logprobs"]:
        if key in body and body[key] is not None:
            params[key] = body[key]
    return params


def inject_fallback_info(content: str, provider: str, model: str, reason: str) -> str:
    """在内容前注入回退信息"""
    fallback_msg = f"[openfish]回退到 {provider}/{model}，失败原因: {reason}[openfish-end]\n\n"
    return fallback_msg + (content or "")


@router.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """OpenAI兼容的chat/completions端点"""
    app = get_app()
    hc = get_health_checker()

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

    estimated_tokens = estimate_tokens(messages)
    request_params = extract_request_params(body)

    # 获取路由配置
    route = app.config.routes[0] if app.config.routes else None
    fallback_order = route.fallback_order if route else []

    # 构建回退列表
    fallback_targets = []
    
    if raw_model.startswith("back-"):
        route_name = raw_model[5:]
        for r in app.config.routes:
            if r.name == route_name:
                fallback_targets = r.fallback_order.copy()
                break
        if not fallback_targets:
            for b in app.config.backends:
                if b.enabled:
                    for m in b.models:
                        if m.enabled:
                            fallback_targets.append(f"{b.name}/{m.id}")
    else:
        found = False
        for b in app.config.backends:
            if not b.enabled:
                continue
            for m in b.models:
                if m.id == raw_model and m.enabled:
                    fallback_targets.insert(0, f"{b.name}/{m.id}")
                    found = True
                    break
        for target in fallback_order:
            if target not in fallback_targets:
                fallback_targets.append(target)
        if not found:
            for b in app.config.backends:
                if b.enabled:
                    for m in b.models:
                        if m.enabled:
                            fallback_targets.append(f"{b.name}/{m.id}")

    # 去重
    seen = set()
    unique_targets = []
    for t in fallback_targets:
        base = t.split("/")[0] if "/" not in t else t
        if base not in seen:
            seen.add(base)
            unique_targets.append(t)
    fallback_targets = unique_targets

    # 尝试每个目标
    last_error = None
    tried = []

    for target in fallback_targets:
        provider_name, model_id = parse_fallback_target(target)
        
        # 检查后端是否存在
        if provider_name not in app.backends:
            last_error = f"后端 {provider_name} 不存在"
            continue
        
        backend = app.backends[provider_name]
        
        # 检查健康状态
        if not backend.status.healthy:
            last_error = f"{provider_name} 不健康"
            continue
        
        # 检查是否被速率限制临时禁用
        if hc.is_rate_limited(provider_name, model_id or ""):
            last_error = f"{provider_name}/{model_id or '*'} 速率限制冷却中"
            tried.append(target)
            continue
        
        backend_config = app.config.get_backend_by_name(provider_name)
        if not backend_config:
            continue
        
        # 查找模型
        model_config = None
        actual_model = model_id
        if model_id:
            for m in backend_config.models:
                if m.id == model_id:
                    model_config = m
                    actual_model = m.name
                    break
        else:
            for m in backend_config.models:
                if m.enabled:
                    model_config = m
                    actual_model = m.name
                    model_id = m.id
                    break
        
        if not model_config:
            last_error = f"{provider_name} 未找到模型 {model_id}"
            continue
        
        # 检查上下文长度
        if model_config.context_length > 0 and estimated_tokens > model_config.context_length:
            last_error = f"{model_id} 上下文不足 ({estimated_tokens} > {model_config.context_length})"
            tried.append(target)
            continue
        
        # 检查速率限制
        if not await rate_limiter.can_request(provider_name, estimated_tokens):
            last_error = f"{provider_name} 速率限制"
            # 标记为速率限制，60秒后恢复
            hc.mark_rate_limited(provider_name, "", 60)
            tried.append(target)
            continue
        
        # 尝试请求
        await rate_limiter.acquire(provider_name, estimated_tokens)
        start_time = time.time()
        
        try:
            if stream:
                need_fallback = len(tried) > 0
                return StreamingResponse(
                    stream_with_fallback(
                        backend, actual_model, messages, request_params, start_time,
                        provider_name, model_id or "", last_error if need_fallback else None
                    ),
                    media_type="text/event-stream"
                )
            else:
                result = await backend.chat_completion(
                    model=actual_model,
                    messages=messages,
                    stream=False,
                    **request_params
                )
                
                latency = time.time() - start_time
                tokens = result.get("usage", {}).get("total_tokens", 0)
                await stats.record(raw_model, provider_name, tokens, latency, True)
                
                # 如果有回退，注入信息
                if tried and last_error:
                    if "choices" in result and result["choices"]:
                        choice = result["choices"][0]
                        if "message" in choice and "content" in choice["message"]:
                            original = choice["message"]["content"] or ""
                            choice["message"]["content"] = inject_fallback_info(
                                original, provider_name, model_id or "", last_error
                            )
                
                return result
                
        except Exception as e:
            latency = time.time() - start_time
            await stats.record(raw_model, provider_name, 0, latency, False)
            last_error = f"{provider_name}/{model_id} 请求失败: {str(e)}"
            logger.error(f"Chat error for {target}: {e}")
            tried.append(target)
        finally:
            rate_limiter.release(provider_name)

    raise HTTPException(status_code=503, detail=f"所有后端都不可用。最后错误: {last_error}")


async def stream_with_fallback(
    backend, model: str, messages: List[Dict], params: Dict, start_time: float,
    provider: str, model_id: str, fail_reason: Optional[str]
):
    """流式响应（带回退信息）"""
    try:
        if fail_reason:
            fallback_msg = f"[openfish]回退到 {provider}/{model_id}，失败原因: {fail_reason}[openfish-end]\n\n"
            chunk = {
                "id": "chatcmpl-openfish",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model,
                "choices": [{"index": 0, "delta": {"content": fallback_msg}, "finish_reason": None}]
            }
            yield f"data: {json.dumps(chunk)}\n\n"
        
        async for chunk in backend.chat_completion_stream(model=model, messages=messages, **params):
            yield f"data: {json.dumps(chunk)}\n\n"

        yield "data: [DONE]\n\n"

        latency = time.time() - start_time
        await stats.record(model, backend.name, 0, latency, True)

    except Exception as e:
        latency = time.time() - start_time
        await stats.record(model, backend.name, 0, latency, False)
        logger.error(f"Stream error: {e}")
        yield f"data: {json.dumps({'error': {'message': str(e), 'type': 'server_error'}})}\n\n"
    finally:
        rate_limiter.release(backend.name)
