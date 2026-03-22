"""Google Generative AI后端适配器"""
import asyncio
import json
import time
import base64
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

    def _get_mime_type_from_data(self, data: str) -> str:
        """从base64数据推断MIME类型"""
        if data.startswith("/9j/"):
            return "image/jpeg"
        elif data.startswith("iVBOR"):
            return "image/png"
        elif data.startswith("UklG"):
            return "image/webp"
        elif data.startswith("R0lG"):
            return "image/gif"
        return "image/jpeg"

    def _convert_messages(self, messages: List[Dict]) -> tuple[Dict | None, List[Dict]]:
        """转换OpenAI格式消息为Google格式（支持多模态）"""
        system_instruction = None
        contents = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "system":
                if isinstance(content, list):
                    text = " ".join(p.get("text", "") for p in content if p.get("type") == "text")
                else:
                    text = str(content)
                system_instruction = {"parts": [{"text": text}]}
            else:
                google_role = "model" if role == "assistant" else "user"
                parts = []

                if isinstance(content, list):
                    # 多模态内容
                    for part in content:
                        if part.get("type") == "text":
                            parts.append({"text": part.get("text", "")})
                        elif part.get("type") == "image_url":
                            image_url = part.get("image_url", {}).get("url", "")
                            if image_url.startswith("data:"):
                                # data:image/jpeg;base64,...
                                mime_type = image_url.split(";")[0].split(":")[1] if ":" in image_url else "image/jpeg"
                                base64_data = image_url.split(",", 1)[1] if "," in image_url else ""
                                parts.append({
                                    "inlineData": {
                                        "mimeType": mime_type,
                                        "data": base64_data
                                    }
                                })
                            else:
                                # URL图片
                                parts.append({
                                    "fileData": {
                                        "mimeType": "image/*",
                                        "fileUri": image_url
                                    }
                                })
                        elif part.get("type") == "image_base64":
                            data = part.get("data", "")
                            mime_type = part.get("media_type") or self._get_mime_type_from_data(data)
                            parts.append({
                                "inlineData": {
                                    "mimeType": mime_type,
                                    "data": data
                                }
                            })
                else:
                    parts.append({"text": str(content)})

                contents.append({"role": google_role, "parts": parts})

        return system_instruction, contents

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
            system_instruction, contents = self._convert_messages(messages)

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

            # Google Gemini支持function calling
            if kwargs.get("tools"):
                google_tools = []
                for tool in kwargs["tools"]:
                    if tool.get("type") == "function":
                        func = tool.get("function", {})
                        google_tools.append({
                            "functionDeclarations": [{
                                "name": func.get("name", ""),
                                "description": func.get("description", ""),
                                "parameters": func.get("parameters", {})
                            }]
                        })
                    else:
                        google_tools.append(tool)
                payload["tools"] = google_tools
            if kwargs.get("tool_choice"):
                # 转换tool_choice
                choice = kwargs["tool_choice"]
                if choice == "auto":
                    payload["toolConfig"] = {"functionCallingConfig": {"mode": "AUTO"}}
                elif choice == "none":
                    payload["toolConfig"] = {"functionCallingConfig": {"mode": "NONE"}}
                elif choice == "any" or choice == "required":
                    payload["toolConfig"] = {"functionCallingConfig": {"mode": "ANY"}}
                elif isinstance(choice, dict) and choice.get("type") == "function":
                    payload["toolConfig"] = {
                        "functionCallingConfig": {
                            "mode": "ANY",
                            "allowedFunctionNames": [choice.get("function", {}).get("name", "")]
                        }
                    }

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
            system_instruction, contents = self._convert_messages(messages)

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

    async def list_models(self) -> List[Dict[str, Any]]:
        """列出可用模型（调用API获取）"""
        client = await self._get_client()
        try:
            url = f"{self.url}/v1beta/models"
            if self.api_key:
                url += f"?key={self.api_key}"
            
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
            
            models = []
            for m in data.get("models", []):
                # 只返回生成模型
                supported_methods = m.get("supportedGenerationMethods", [])
                if "generateContent" in supported_methods:
                    model_info = {
                        "id": m.get("name", "").replace("models/", ""),
                        "name": m.get("displayName", ""),
                        "context_length": m.get("inputTokenLimit") or 32768,
                        "max_tokens": m.get("outputTokenLimit") or 8192,
                        "description": m.get("description", ""),
                    }
                    models.append(model_info)
            return models
        except Exception as e:
            logger.error(f"Google list models error: {e}")
            # 返回默认模型列表
            return [
                {"id": "gemini-1.5-pro", "name": "Gemini 1.5 Pro", "context_length": 1000000},
                {"id": "gemini-1.5-flash", "name": "Gemini 1.5 Flash", "context_length": 1000000},
                {"id": "gemini-1.0-pro", "name": "Gemini 1.0 Pro", "context_length": 32768},
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
