"""Ollama后端适配器"""
import asyncio
import json
import time
from typing import Any, AsyncIterator, Dict, List
import httpx

from .base import BaseBackend

import logging
logger = logging.getLogger("openfish.backends.ollama")


class OllamaBackend(BaseBackend):
    """Ollama后端"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """获取HTTP客户端"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout, connect=10),
                verify=self.verify_ssl
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
            # 转换为Ollama格式
            ollama_messages = []
            for msg in messages:
                ollama_messages.append({
                    "role": msg.get("role", "user"),
                    "content": msg.get("content", "")
                })

            payload = {
                "model": model,
                "messages": ollama_messages,
                "stream": False,
                "options": {}
            }

            if kwargs.get("temperature") is not None:
                payload["options"]["temperature"] = kwargs["temperature"]
            if kwargs.get("max_tokens") is not None:
                payload["options"]["num_predict"] = kwargs["max_tokens"]

            response = await client.post(
                f"{self.url}/api/chat",
                json=payload
            )
            response.raise_for_status()
            result = response.json()

            latency = time.time() - start_time
            self.update_status(True, latency)

            # 转换为OpenAI格式
            return self._to_openai_format(result, model)

        except Exception as e:
            latency = time.time() - start_time
            self.update_status(False, latency)
            logger.error(f"Ollama chat error: {e}")
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
            ollama_messages = []
            for msg in messages:
                ollama_messages.append({
                    "role": msg.get("role", "user"),
                    "content": msg.get("content", "")
                })

            payload = {
                "model": model,
                "messages": ollama_messages,
                "stream": True,
                "options": {}
            }

            if kwargs.get("temperature") is not None:
                payload["options"]["temperature"] = kwargs["temperature"]
            if kwargs.get("max_tokens") is not None:
                payload["options"]["num_predict"] = kwargs["max_tokens"]

            async with client.stream(
                "POST",
                f"{self.url}/api/chat",
                json=payload
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        chunk = self._to_openai_stream_chunk(data, model)
                        yield chunk
                    except json.JSONDecodeError:
                        continue

            latency = time.time() - start_time
            self.update_status(True, latency)

        except Exception as e:
            latency = time.time() - start_time
            self.update_status(False, latency)
            logger.error(f"Ollama stream error: {e}")
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
            texts = [input_text] if isinstance(input_text, str) else input_text
            embeddings = []

            for text in texts:
                response = await client.post(
                    f"{self.url}/api/embeddings",
                    json={"model": model, "prompt": text}
                )
                response.raise_for_status()
                result = response.json()
                embeddings.append(result.get("embedding", []))

            latency = time.time() - start_time
            self.update_status(True, latency)

            return {
                "object": "list",
                "data": [
                    {"object": "embedding", "embedding": emb, "index": i}
                    for i, emb in enumerate(embeddings)
                ],
                "model": model,
                "usage": {"prompt_tokens": 0, "total_tokens": 0}
            }

        except Exception as e:
            latency = time.time() - start_time
            self.update_status(False, latency)
            logger.error(f"Ollama embedding error: {e}")
            raise

    async def list_models(self) -> List[str]:
        """列出可用模型"""
        client = await self._get_client()
        try:
            response = await client.get(f"{self.url}/api/tags")
            response.raise_for_status()
            data = response.json()
            return [m["name"] for m in data.get("models", [])]
        except Exception as e:
            logger.error(f"Ollama list models error: {e}")
            return []

    async def health_check(self) -> bool:
        """健康检查"""
        try:
            client = await self._get_client()
            response = await client.get(f"{self.url}/api/tags", timeout=5)
            healthy = response.status_code == 200
            self.update_status(healthy, 0)
            return healthy
        except Exception:
            self.update_status(False, 0)
            return False

    def _to_openai_format(self, data: Dict, model: str) -> Dict:
        """转换为OpenAI格式"""
        message = data.get("message", {})
        return {
            "id": f"chatcmpl-{self.name}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": message.get("content", "")
                },
                "finish_reason": "stop"
            }],
            "usage": {
                "prompt_tokens": data.get("prompt_eval_count", 0),
                "completion_tokens": data.get("eval_count", 0),
                "total_tokens": data.get("prompt_eval_count", 0) + data.get("eval_count", 0)
            }
        }

    def _to_openai_stream_chunk(self, data: Dict, model: str) -> Dict:
        """转换为OpenAI流式格式"""
        message = data.get("message", {})
        done = data.get("done", False)

        return {
            "id": f"chatcmpl-{self.name}",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model,
            "choices": [{
                "index": 0,
                "delta": {
                    "role": "assistant" if not done else None,
                    "content": message.get("content", "")
                },
                "finish_reason": "stop" if done else None
            }]
        }

    async def close(self) -> None:
        """关闭连接"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
