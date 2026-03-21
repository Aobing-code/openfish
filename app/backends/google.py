"""Google Generative AI后端适配器"""
import asyncio
import json
import time
from typing import Any, AsyncIterator, Dict, List
import httpx

from .base import BaseBackend

import logging
logger = logging.getLogger("openfish.backends.google")


class GoogleBackend(BaseBackend):
    """Google Gemini后端"""

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
            # 转换为Google格式
            contents = []
            system_instruction = None

            for msg in messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")

                if role == "system":
                    system_instruction = {"parts": [{"text": content}]}
                else:
                    google_role = "model" if role == "assistant" else "user"
                    contents.append({
                        "role": google_role,
                        "parts": [{"text": content}]
                    })

            payload: Dict[str, Any] = {
                "contents": contents,
                "generationConfig": {}
            }

            if system_instruction:
                payload["systemInstruction"] = system_instruction
            if kwargs.get("temperature") is not None:
                payload["generationConfig"]["temperature"] = kwargs["temperature"]
            if kwargs.get("max_tokens") is not None:
                payload["generationConfig"]["maxOutputTokens"] = kwargs["max_tokens"]
            if kwargs.get("top_p") is not None:
                payload["generationConfig"]["topP"] = kwargs["top_p"]

            url = f"{self.url}/v1beta/models/{model}:generateContent"
            if self.api_key:
                url += f"?key={self.api_key}"

            response = await client.post(url, json=payload)
            response.raise_for_status()
            result = response.json()

            latency = time.time() - start_time
            self.update_status(True, latency)

            return self._to_openai_format(result, model)

        except Exception as e:
            latency = time.time() - start_time
            self.update_status(False, latency)
            logger.error(f"Google chat error: {e}")
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
            contents = []
            system_instruction = None

            for msg in messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")

                if role == "system":
                    system_instruction = {"parts": [{"text": content}]}
                else:
                    google_role = "model" if role == "assistant" else "user"
                    contents.append({
                        "role": google_role,
                        "parts": [{"text": content}]
                    })

            payload: Dict[str, Any] = {
                "contents": contents,
                "generationConfig": {}
            }

            if system_instruction:
                payload["systemInstruction"] = system_instruction
            if kwargs.get("temperature") is not None:
                payload["generationConfig"]["temperature"] = kwargs["temperature"]
            if kwargs.get("max_tokens") is not None:
                payload["generationConfig"]["maxOutputTokens"] = kwargs["max_tokens"]

            url = f"{self.url}/v1beta/models/{model}:streamGenerateContent?alt=sse"
            if self.api_key:
                url += f"&key={self.api_key}"

            async with client.stream("POST", url, json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    try:
                        data = json.loads(data_str)
                        chunk = self._to_openai_stream_chunk(data, model)
                        if chunk:
                            yield chunk
                    except json.JSONDecodeError:
                        continue

            latency = time.time() - start_time
            self.update_status(True, latency)

        except Exception as e:
            latency = time.time() - start_time
            self.update_status(False, latency)
            logger.error(f"Google stream error: {e}")
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
                embed_model = model if "embed" in model else "text-embedding-004"
                url = f"{self.url}/v1beta/models/{embed_model}:embedContent"
                if self.api_key:
                    url += f"?key={self.api_key}"

                payload = {
                    "model": embed_model,
                    "content": {"parts": [{"text": text}]}
                }

                response = await client.post(url, json=payload)
                response.raise_for_status()
                result = response.json()
                embeddings.append(result.get("embedding", {}).get("values", []))

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
            logger.error(f"Google embedding error: {e}")
            raise

    async def list_models(self) -> List[str]:
        """列出可用模型"""
        return [
            "gemini-1.5-pro",
            "gemini-1.5-flash",
            "gemini-1.0-pro",
            "text-embedding-004"
        ]

    async def health_check(self) -> bool:
        """健康检查"""
        if not self.api_key:
            self.update_status(False, 0)
            return False
        try:
            client = await self._get_client()
            url = f"{self.url}/v1beta/models?key={self.api_key}"
            response = await client.get(url, timeout=10)
            healthy = response.status_code == 200
            self.update_status(healthy, 0)
            return healthy
        except Exception:
            self.update_status(False, 0)
            return False

    def _to_openai_format(self, data: Dict, model: str) -> Dict:
        """转换为OpenAI格式"""
        content = ""
        candidates = data.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            for part in parts:
                if "text" in part:
                    content += part["text"]

        usage = data.get("usageMetadata", {})

        return {
            "id": f"chatcmpl-{self.name}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content
                },
                "finish_reason": "stop"
            }],
            "usage": {
                "prompt_tokens": usage.get("promptTokenCount", 0),
                "completion_tokens": usage.get("candidatesTokenCount", 0),
                "total_tokens": usage.get("totalTokenCount", 0)
            }
        }

    def _to_openai_stream_chunk(self, data: Dict, model: str) -> Dict | None:
        """转换为OpenAI流式格式"""
        candidates = data.get("candidates", [])
        if not candidates:
            return None

        content = ""
        parts = candidates[0].get("content", {}).get("parts", [])
        for part in parts:
            if "text" in part:
                content += part["text"]

        finish_reason = None
        if candidates[0].get("finishReason") == "STOP":
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
