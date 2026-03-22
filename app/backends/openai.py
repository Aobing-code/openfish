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

            # 透传所有支持的参数
            for key in ["temperature", "max_tokens", "top_p", "frequency_penalty", 
                        "presence_penalty", "stop", "n", "seed", "response_format",
                        "tools", "tool_choice", "functions", "function_call",
                        "logprobs", "top_logprobs"]:
                if key in kwargs and kwargs[key] is not None:
                    payload[key] = kwargs[key]

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

            # 透传所有支持的参数
            for key in ["temperature", "max_tokens", "top_p", "frequency_penalty",
                        "presence_penalty", "stop", "n", "seed", "response_format",
                        "tools", "tool_choice", "functions", "function_call"]:
                if key in kwargs and kwargs[key] is not None:
                    payload[key] = kwargs[key]

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

    async def list_models(self) -> List[Dict[str, Any]]:
        """列出可用模型（包含详细信息）"""
        client = await self._get_client()
        try:
            response = await client.get(f"{self.url}/models")
            response.raise_for_status()
            data = response.json()
            
            models = []
            for m in data.get("data", []):
                model_info = {
                    "id": m.get("id", ""),
                    "name": m.get("id", ""),
                    "context_length": m.get("context_length") or 4096,
                    "owned_by": m.get("owned_by", ""),
                }
                models.append(model_info)
            return models
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
