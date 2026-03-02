# -*- coding: utf-8 -*-
"""Grok web chat model -- browser-authenticated access to grok.com."""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncGenerator

import aiohttp

from ..web_models import WebCredential
from .base import WebChatModelBase

logger = logging.getLogger(__name__)


class GrokWebChatModel(WebChatModelBase):
    """Chat model using the Grok web interface at grok.com.

    Uses X/Twitter auth cookies. SSE streaming with custom JSON format.
    Grok returns JSON objects (one per line) or SSE data lines.
    """

    def _get_api_url(self) -> str:
        return "https://grok.com"

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
        """Parse Grok SSE events.

        Grok may send:
        - data: {json} format
        - raw JSON per line (no data: prefix)
        - result.contentDelta / result.textDelta fields
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

        res = data.get("result", data)

        # Skip human messages
        if res.get("userResponse", {}).get("sender") == "human":
            return

        # Try various delta field names
        delta = (
            res.get("contentDelta")
            or res.get("textDelta")
            or res.get("content")
            or res.get("text")
            or res.get("markdown")
            or data.get("text")
            or data.get("content")
            or data.get("delta")
        )

        # Fallback to choices format
        if delta is None and "choices" in data:
            delta = data["choices"][0].get("delta", {}).get("content")

        if isinstance(delta, str) and delta:
            yield delta
