"""Anthropic后端适配器"""
import asyncio
import json
import time
from typing import Any, AsyncIterator, Dict, List
import httpx

from .base import BaseBackend

import logging
logger = logging.getLogger("openfish.backends.anthropic")


class AnthropicBackend(BaseBackend):
    """Anthropic Claude后端"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """获取HTTP客户端"""
        if self._client is None or self._client.is_closed:
            headers = {
                "x-api-key": self.api_key or "",
                "anthropic-version": "2023-06-01"
            }
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
            # 转换为Anthropic格式
            system = ""
            anthropic_messages = []

            for msg in messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")

                if role == "system":
                    system = content
                else:
                    anthropic_messages.append({
                        "role": role if role in ["user", "assistant"] else "user",
                        "content": content
                    })

            payload: Dict[str, Any] = {
                "model": model,
                "messages": anthropic_messages,
                "max_tokens": kwargs.get("max_tokens") or 4096,
                "stream": False
            }

            if system:
                payload["system"] = system
            if kwargs.get("temperature") is not None:
                payload["temperature"] = kwargs["temperature"]
            if kwargs.get("top_p") is not None:
                payload["top_p"] = kwargs["top_p"]

            response = await client.post(
                f"{self.url}/v1/messages",
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
            logger.error(f"Anthropic chat error: {e}")
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
            system = ""
            anthropic_messages = []

            for msg in messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")

                if role == "system":
                    system = content
                else:
                    anthropic_messages.append({
                        "role": role if role in ["user", "assistant"] else "user",
                        "content": content
                    })

            payload: Dict[str, Any] = {
                "model": model,
                "messages": anthropic_messages,
                "max_tokens": kwargs.get("max_tokens") or 4096,
                "stream": True
            }

            if system:
                payload["system"] = system
            if kwargs.get("temperature") is not None:
                payload["temperature"] = kwargs["temperature"]

            async with client.stream(
                "POST",
                f"{self.url}/v1/messages",
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
                        chunk = self._to_openai_stream_chunk(data, model)
                        yield chunk
                    except json.JSONDecodeError:
                        continue

            latency = time.time() - start_time
            self.update_status(True, latency)

        except Exception as e:
            latency = time.time() - start_time
            self.update_status(False, latency)
            logger.error(f"Anthropic stream error: {e}")
            raise

    async def embedding(
        self,
        model: str,
        input_text: str | List[str],
        **kwargs
    ) -> Any:
        """向量嵌入 - Anthropic不支持"""
        raise NotImplementedError("Anthropic does not support embeddings")

    async def list_models(self) -> List[str]:
        """列出可用模型"""
        return [
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
            "claude-3-opus-20240229",
            "claude-3-sonnet-20240229",
            "claude-3-haiku-20240307"
        ]

    async def health_check(self) -> bool:
        """健康检查"""
        if not self.api_key:
            self.update_status(False, 0)
            return False
        try:
            client = await self._get_client()
            # 简单检查API Key是否有效
            response = await client.post(
                f"{self.url}/v1/messages",
                json={
                    "model": "claude-3-haiku-20240307",
                    "messages": [{"role": "user", "content": "hi"}],
                    "max_tokens": 1
                },
                timeout=10
            )
            healthy = response.status_code in [200, 400, 401]
            self.update_status(healthy, 0)
            return healthy
        except Exception:
            self.update_status(False, 0)
            return False

    def _to_openai_format(self, data: Dict, model: str) -> Dict:
        """转换为OpenAI格式"""
        content = ""
        if data.get("content"):
            for block in data["content"]:
                if block.get("type") == "text":
                    content += block.get("text", "")

        usage = data.get("usage", {})

        return {
            "id": data.get("id", f"chatcmpl-{self.name}"),
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content
                },
                "finish_reason": "stop" if data.get("stop_reason") == "end_turn" else data.get("stop_reason")
            }],
            "usage": {
                "prompt_tokens": usage.get("input_tokens", 0),
                "completion_tokens": usage.get("output_tokens", 0),
                "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
            }
        }

    def _to_openai_stream_chunk(self, data: Dict, model: str) -> Dict:
        """转换为OpenAI流式格式"""
        event_type = data.get("type", "")
        content = ""

        if event_type == "content_block_delta":
            delta = data.get("delta", {})
            if delta.get("type") == "text_delta":
                content = delta.get("text", "")

        finish_reason = None
        if event_type == "message_stop":
            finish_reason = "stop"

        return {
            "id": f"chatcmpl-{self.name}",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model,
            "choices": [{
                "index": 0,
                "delta": {
                    "content": content
                },
                "finish_reason": finish_reason
            }]
        }

    async def close(self) -> None:
        """关闭连接"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
