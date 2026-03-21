"""API Key认证模块"""
import time
from typing import Optional, Set
from fastapi import HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

import logging
logger = logging.getLogger("openfish.auth")


class APIKeyAuth:
    """API Key认证"""

    def __init__(self, enabled: bool = True, api_keys: list = None):
        self.enabled = enabled
        self.api_keys: Set[str] = set(api_keys or [])
        self.security = HTTPBearer(auto_error=False)

    def verify(self, request: Request) -> bool:
        """验证请求"""
        if not self.enabled:
            return True

        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            api_key = auth_header[7:]
            if api_key in self.api_keys:
                return True

        return False

    def update_keys(self, api_keys: list) -> None:
        """更新API Key列表"""
        self.api_keys = set(api_keys)
        logger.info(f"API keys updated: {len(self.api_keys)} keys")

    def add_key(self, api_key: str) -> None:
        """添加API Key"""
        self.api_keys.add(api_key)

    def remove_key(self, api_key: str) -> None:
        """移除API Key"""
        self.api_keys.discard(api_key)
