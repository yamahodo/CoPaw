# -*- coding: utf-8 -*-
"""GLM web chat model -- browser-authenticated access to chatglm.cn."""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncGenerator

import aiohttp

from ..web_models import WebCredential
from .base import WebChatModelBase

logger = logging.getLogger(__name__)


class GLMWebChatModel(WebChatModelBase):
    """Chat model using the ChatGLM web interface at chatglm.cn.

    Uses chatglm_token cookie for auth.
    SSE format: standard OpenAI-compatible or ChatGLM parts format.

    ChatGLM may return accumulated text in each SSE event, so we compute
    deltas ourselves.
    """

    def __init__(
        self,
        model_name: str,
        credential: WebCredential,
        stream: bool = True,
    ) -> None:
        super().__init__(model_name, credential, stream)
        self._last_extracted_text = ""

    def _get_api_url(self) -> str:
        return "https://chatglm.cn"

    async def _send_message(
        self,
        prompt: str,
        headers: dict[str, str],
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        url = f"{self._get_api_url()}/api/paas/v4/chat/completions"

        body = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
        }

        self._last_extracted_text = ""

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

    def _parse_sse_line(self, line: str):
        """Parse ChatGLM SSE events.

        ChatGLM may use:
        1. Parts format: {"parts":[{"content":[{"type":"text","text":"..."}]}]}
           where text is accumulated (need delta computation)
        2. Standard delta format
        3. Legacy {"text":"..."} format
        """
        data_str = line.strip()
        if data_str.startswith("data:"):
            data_str = data_str[5:].strip()
        if not data_str or data_str == "[DONE]":
            return

        try:
            data = json.loads(data_str)
        except json.JSONDecodeError:
            return

        # Skip error or init status
        if data.get("status") == "error":
            err_msg = data.get("last_error", {}).get("message", "Unknown error")
            logger.warning("ChatGLM API error: %s", err_msg)
            return
        if data.get("status") == "init":
            return

        # Parts format (new ChatGLM API)
        full_text = ""
        if "parts" in data and isinstance(data["parts"], list):
            full_text = self._extract_text_from_parts(data["parts"])

        # Fallback to legacy format
        if not full_text:
            full_text = data.get("text", "")

        if full_text and full_text != self._last_extracted_text:
            delta = full_text[len(self._last_extracted_text):]
            self._last_extracted_text = full_text
            if delta:
                yield delta

    @staticmethod
    def _extract_text_from_parts(parts: list) -> str:
        """Extract text from ChatGLM parts format.

        Format: parts[].content[] where content items have {type: "text", text: "..."}
        """
        for part in parts:
            if not isinstance(part, dict):
                continue
            content = part.get("content")
            if isinstance(content, list):
                for item in content:
                    if (
                        isinstance(item, dict)
                        and item.get("type") == "text"
                        and isinstance(item.get("text"), str)
                    ):
                        return item["text"]
        return ""
