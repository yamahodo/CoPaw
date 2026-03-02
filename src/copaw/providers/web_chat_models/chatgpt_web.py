# -*- coding: utf-8 -*-
"""ChatGPT web chat model -- browser-authenticated access to chatgpt.com."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, AsyncGenerator

import aiohttp

from ..web_models import WebCredential
from .base import WebChatModelBase

logger = logging.getLogger(__name__)


class ChatGPTWebChatModel(WebChatModelBase):
    """Chat model using the ChatGPT web interface at chatgpt.com.

    Sends messages via POST /backend-api/conversation.
    SSE format: data: {"message":{"content":{"parts":["..."]}}}
    """

    def __init__(
        self,
        model_name: str,
        credential: WebCredential,
        stream: bool = True,
    ) -> None:
        super().__init__(model_name, credential, stream)
        self._conversation_id: str | None = None
        self._parent_message_id: str | None = None

    def _get_api_url(self) -> str:
        return "https://chatgpt.com"

    def _build_headers(self) -> dict[str, str]:
        headers = super()._build_headers()
        headers["oai-language"] = "en-US"
        # ChatGPT may use bearer token from session
        if self._credential.bearer:
            headers["Authorization"] = f"Bearer {self._credential.bearer}"
        return headers

    async def _send_message(
        self,
        prompt: str,
        headers: dict[str, str],
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        url = f"{self._get_api_url()}/backend-api/conversation"

        message_id = str(uuid.uuid4())
        parent_id = self._parent_message_id or str(uuid.uuid4())

        body: dict[str, Any] = {
            "action": "next",
            "messages": [
                {
                    "id": message_id,
                    "author": {"role": "user"},
                    "content": {
                        "content_type": "text",
                        "parts": [prompt],
                    },
                }
            ],
            "parent_message_id": parent_id,
            "model": self.model_name,
            "history_and_training_disabled": False,
            "conversation_mode": {"kind": "primary_assistant"},
            "force_use_sse": True,
        }

        if self._conversation_id:
            body["conversation_id"] = self._conversation_id

        accumulated_content = ""

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
                        for text in self._parse_sse_line(
                            line, accumulated_content
                        ):
                            accumulated_content += text
                            yield text

                if buffer.strip():
                    for text in self._parse_sse_line(
                        buffer.strip(), accumulated_content
                    ):
                        accumulated_content += text
                        yield text

    def _parse_sse_line(self, line: str, accumulated: str):
        """Parse ChatGPT SSE events.

        ChatGPT sends the full accumulated content in each event, so we
        compute the delta ourselves.
        """
        if not line.startswith("data:"):
            return
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            return

        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return

        # Track conversation/message state
        if data.get("conversation_id"):
            self._conversation_id = data["conversation_id"]
        if data.get("message", {}).get("id"):
            self._parent_message_id = data["message"]["id"]

        # Only process assistant messages
        role = (
            data.get("message", {}).get("author", {}).get("role")
            or data.get("message", {}).get("role")
        )
        if role and role != "assistant":
            return

        # Extract content from parts
        raw_part = (
            data.get("message", {}).get("content", {}).get("parts", [None])[0]
        )
        content: str | None = None
        if isinstance(raw_part, str):
            content = raw_part
        elif isinstance(raw_part, dict) and "text" in raw_part:
            content = raw_part["text"]

        if isinstance(content, str) and content:
            delta = content[len(accumulated):]
            if delta:
                yield delta
