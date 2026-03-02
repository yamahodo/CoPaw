# -*- coding: utf-8 -*-
"""Doubao web chat model -- browser-authenticated access to www.doubao.com."""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncGenerator

import aiohttp

from ..web_models import WebCredential
from .base import WebChatModelBase

logger = logging.getLogger(__name__)


class DoubaoWebChatModel(WebChatModelBase):
    """Chat model using the Doubao (ByteDance) web interface.

    Doubao uses a custom SSE format with nested JSON:
    data: {"event_type":2001,"event_data":"{\\"message\\":{\\"content\\":\\"...\\"}}"}
    """

    def _get_api_url(self) -> str:
        return "https://www.doubao.com"

    def _build_headers(self) -> dict[str, str]:
        headers = super()._build_headers()
        # Doubao uses session_id and ttwid cookies
        return headers

    async def _send_message(
        self,
        prompt: str,
        headers: dict[str, str],
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        # Doubao passes full message history
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
        """Parse Doubao SSE events.

        Format 1 (samantha API): {"event_type":2001,"event_data":"{...}"}
          where event_data is a JSON string containing message.content (also JSON string)
        Format 2 (fallback): standard data fields
        """
        data_str = line
        if line.startswith("data:"):
            data_str = line[5:].strip()
        if not data_str or data_str == "[DONE]":
            return

        try:
            data = json.loads(data_str)
        except json.JSONDecodeError:
            return

        # Doubao samantha API format
        if data.get("event_type") == 2001 and data.get("event_data"):
            try:
                event_data = json.loads(data["event_data"])
                content_raw = event_data.get("message", {}).get("content", "")
                if content_raw:
                    try:
                        content_obj = json.loads(content_raw)
                        text = content_obj.get("text", "")
                        if text:
                            yield text
                    except json.JSONDecodeError:
                        # content_raw is plain text
                        yield content_raw
            except json.JSONDecodeError:
                pass
        elif data.get("event_type") == 2003:
            # Stream end marker
            return
