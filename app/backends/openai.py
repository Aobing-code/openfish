"""OpenAI兼容后端适配器（支持OpenAI/Deepseek/通义千问/智谱等）"""
import asyncio
import json
import time
from typing import Any, AsyncIterator, Dict, List
import httpx

from .base import BaseBackend

import logging
logger = logging.getLogger("openfish.backends.openai")


class OpenAIBackend(BaseBackend):
    """OpenAI兼容后端"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """获取HTTP客户端"""
        if self._client is None or self._client.is_closed:
            headers = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout, connect=10),
                verify=self.verify_ssl,
                headers=headers
            )
        return self._client

    async def chat_completion(
        self,
        model: str,
        messages: List[Dict[str, str]],
        stream: bool = False,
        **kwargs
    ) -> Any:
        """聊天补全"""
        client = await self._get_client()
        start_time = time.time()

        try:
            payload = {
                "model": model,
                "messages": messages,
                "stream": False
            }

            if kwargs.get("temperature") is not None:
                payload["temperature"] = kwargs["temperature"]
            if kwargs.get("max_tokens") is not None:
                payload["max_tokens"] = kwargs["max_tokens"]
            if kwargs.get("top_p") is not None:
                payload["top_p"] = kwargs["top_p"]

            response = await client.post(
                f"{self.url}/chat/completions",
                json=payload
            )
            response.raise_for_status()
            result = response.json()

            latency = time.time() - start_time
            self.update_status(True, latency)

            return result

        except Exception as e:
            latency = time.time() - start_time
            self.update_status(False, latency)
            logger.error(f"OpenAI chat error: {e}")
            raise

    async def chat_completion_stream(
        self,
        model: str,
        messages: List[Dict[str, str]],
        **kwargs
    ) -> AsyncIterator[Dict[str, Any]]:
        """流式聊天补全"""
        client = await self._get_client()
        start_time = time.time()

        try:
            payload = {
                "model": model,
                "messages": messages,
                "stream": True
            }

            if kwargs.get("temperature") is not None:
                payload["temperature"] = kwargs["temperature"]
            if kwargs.get("max_tokens") is not None:
                payload["max_tokens"] = kwargs["max_tokens"]
            if kwargs.get("top_p") is not None:
                payload["top_p"] = kwargs["top_p"]

            async with client.stream(
                "POST",
                f"{self.url}/chat/completions",
                json=payload
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                        yield data
                    except json.JSONDecodeError:
                        continue

            latency = time.time() - start_time
            self.update_status(True, latency)

        except Exception as e:
            latency = time.time() - start_time
            self.update_status(False, latency)
            logger.error(f"OpenAI stream error: {e}")
            raise

    async def embedding(
        self,
        model: str,
        input_text: str | List[str],
        **kwargs
    ) -> Any:
        """向量嵌入"""
        client = await self._get_client()
        start_time = time.time()

        try:
            payload = {
                "model": model,
                "input": input_text
            }

            response = await client.post(
                f"{self.url}/embeddings",
                json=payload
            )
            response.raise_for_status()
            result = response.json()

            latency = time.time() - start_time
            self.update_status(True, latency)

            return result

        except Exception as e:
            latency = time.time() - start_time
            self.update_status(False, latency)
            logger.error(f"OpenAI embedding error: {e}")
            raise

    async def list_models(self) -> List[str]:
        """列出可用模型"""
        client = await self._get_client()
        try:
            response = await client.get(f"{self.url}/models")
            response.raise_for_status()
            data = response.json()
            return [m["id"] for m in data.get("data", [])]
        except Exception as e:
            logger.error(f"OpenAI list models error: {e}")
            return []

    async def health_check(self) -> bool:
        """健康检查"""
        try:
            client = await self._get_client()
            response = await client.get(f"{self.url}/models", timeout=5)
            healthy = response.status_code == 200
            self.update_status(healthy, 0)
            return healthy
        except Exception:
            self.update_status(False, 0)
            return False

    async def close(self) -> None:
        """关闭连接"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
