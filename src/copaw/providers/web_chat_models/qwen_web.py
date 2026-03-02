# -*- coding: utf-8 -*-
"""Qwen web chat model -- browser-authenticated access to chat.qwen.ai."""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncGenerator

import aiohttp

from ..web_models import WebCredential
from .base import WebChatModelBase

logger = logging.getLogger(__name__)


class QwenWebChatModel(WebChatModelBase):
    """Chat model using the Qwen web interface at chat.qwen.ai.

    POST /api/chat/completions with SSE streaming.
    SSE format: data: {"choices":[{"delta":{"content":"..."}}]}
    """

    def _get_api_url(self) -> str:
        return "https://chat.qwen.ai"

    async def _send_message(
        self,
        prompt: str,
        headers: dict[str, str],
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        url = f"{self._get_api_url()}/api/chat/completions"

        body = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=body) as resp:
                resp.raise_for_status()
                buffer = ""
                async for raw_chunk in resp.content.iter_any():
                    buffer += raw_chunk.decode("utf-8", errors="replace")
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line = line.strip()
                        if not line:
                            continue
                        for text in self._parse_sse_line(line):
                            yield text

                if buffer.strip():
                    for text in self._parse_sse_line(buffer.strip()):
                        yield text

    @staticmethod
    def _parse_sse_line(line: str):
        """Parse Qwen SSE -- standard OpenAI-compatible choices format."""
        if not line.startswith("data:"):
            return
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            return

        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return

        # choices[0].delta.content
        delta = (
            data.get("choices", [{}])[0].get("delta", {}).get("content")
            if "choices" in data
            else data.get("text") or data.get("content") or data.get("delta")
        )
        if isinstance(delta, str) and delta:
            yield delta
