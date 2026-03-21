"""后端模块"""
from .base import BaseBackend, BackendStatus
from .ollama import OllamaBackend
from .openai import OpenAIBackend
from .anthropic import AnthropicBackend
from .google import GoogleBackend

__all__ = [
    "BaseBackend", "BackendStatus",
    "OllamaBackend", "OpenAIBackend",
    "AnthropicBackend", "GoogleBackend"
]


def create_backend(backend_config) -> BaseBackend:
    """根据配置创建后端实例"""
    # 获取第一个API Key（如果有多个）
    api_key = None
    if backend_config.api_keys:
        api_key = backend_config.api_keys[0]

    # 转换模型配置为名称列表
    model_names = [m.name for m in backend_config.models] if backend_config.models else ["*"]

    kwargs = {
        "name": backend_config.name,
        "url": backend_config.url,
        "api_key": api_key,
        "api_keys": backend_config.api_keys,  # 传递所有Key
        "weight": backend_config.weight,
        "timeout": backend_config.timeout,
        "verify_ssl": backend_config.verify_ssl,
        "models": model_names
    }

    backend_type = backend_config.type.lower()

    if backend_type == "ollama":
        return OllamaBackend(**kwargs)
    elif backend_type == "openai":
        return OpenAIBackend(**kwargs)
    elif backend_type == "anthropic":
        return AnthropicBackend(**kwargs)
    elif backend_type == "google":
        return GoogleBackend(**kwargs)
    else:
        return OpenAIBackend(**kwargs)
