"""Models API端点"""
from typing import Dict, Any, List
from fastapi import APIRouter, HTTPException

import logging
logger = logging.getLogger("openfish.api.models")

router = APIRouter()

# 将在main.py中注入
backends_manager = None


@router.get("/v1/models")
async def list_models():
    """列出所有可用模型"""
    all_models = set()

    for backend in backends_manager.values():
        if not backend.status.healthy:
            continue
        if "*" in backend.models:
            # 获取后端实际可用模型
            try:
                models = await backend.list_models()
                all_models.update(models)
            except Exception as e:
                logger.error(f"Failed to list models from {backend.name}: {e}")
        else:
            all_models.update(backend.models)

    models_list = [
        {
            "id": model,
            "object": "model",
            "created": 0,
            "owned_by": "openfish"
        }
        for model in sorted(all_models)
    ]

    return {
        "object": "list",
        "data": models_list
    }


@router.get("/v1/models/{model_id}")
async def get_model(model_id: str):
    """获取指定模型信息"""
    return {
        "id": model_id,
        "object": "model",
        "created": 0,
        "owned_by": "openfish"
    }
