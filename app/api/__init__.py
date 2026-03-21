"""API模块"""
from .chat import router as chat_router
from .embeddings import router as embeddings_router
from .models import router as models_router
from .monitor import router as monitor_router
from .config import router as config_router

__all__ = ["chat_router", "embeddings_router", "models_router", "monitor_router", "config_router"]
