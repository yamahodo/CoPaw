# -*- coding: utf-8 -*-
"""Claude web chat model -- browser-authenticated access to claude.ai."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, AsyncGenerator

import aiohttp

from ..web_models import WebCredential
from .base import WebChatModelBase

logger = logging.getLogger(__name__)


class ClaudeWebChatModel(WebChatModelBase):
    """Chat model using the Claude web interface at claude.ai.

    Auth flow:
    1. GET /api/organizations -> first org uuid
    2. POST /api/organizations/{org_id}/chat_conversations -> create conversation
    3. POST /api/organizations/{org_id}/chat_conversations/{conv_id}/completion -> stream
    """

    def __init__(
        self,
        model_name: str,
        credential: WebCredential,
        stream: bool = True,
    ) -> None:
        super().__init__(model_name, credential, stream)
        self._org_id: str | None = None
        self._device_id: str = self._extract_device_id() or str(uuid.uuid4())

    def _get_api_url(self) -> str:
        return "https://claude.ai/api"

    def _extract_device_id(self) -> str | None:
        """Extract anthropic-device-id from cookie if present."""
        cookie = self._credential.cookie
        if "anthropic-device-id=" in cookie:
            for part in cookie.split(";"):
                part = part.strip()
                if part.startswith("anthropic-device-id="):
                    return part.split("=", 1)[1]
        return None

    def _build_headers(self) -> dict[str, str]:
        headers = super()._build_headers()
        headers["anthropic-client-platform"] = "web_claude_ai"
        headers["anthropic-device-id"] = self._device_id
        # Claude uses sessionKey cookie for auth
        if self._credential.session_key and "sessionKey=" not in headers.get("Cookie", ""):
            existing = headers.get("Cookie", "")
            sk_cookie = f"sessionKey={self._credential.session_key}"
            headers["Cookie"] = f"{existing}; {sk_cookie}" if existing else sk_cookie
        return headers

    # ------------------------------------------------------------------
    # Organization discovery
    # ------------------------------------------------------------------

    async def _ensure_org_id(
        self,
        session: aiohttp.ClientSession,
        headers: dict[str, str],
    ) -> str:
        if self._org_id:
            return self._org_id

        url = f"{self._get_api_url()}/organizations"
        async with session.get(url, headers=headers) as resp:
            resp.raise_for_status()
            data = await resp.json()

        if isinstance(data, list) and data:
            self._org_id = data[0].get("uuid", "")
            logger.info("Claude org discovered: %s", self._org_id)
        if not self._org_id:
            raise RuntimeError("Failed to discover Claude organization")
        return self._org_id

    # ------------------------------------------------------------------
    # Conversation management
    # ------------------------------------------------------------------

    async def _create_conversation(
        self,
        session: aiohttp.ClientSession,
        headers: dict[str, str],
        org_id: str,
    ) -> str:
        url = f"{self._get_api_url()}/organizations/{org_id}/chat_conversations"
        conv_uuid = str(uuid.uuid4())
        body = {"name": "", "uuid": conv_uuid}
        async with session.post(url, headers=headers, json=body) as resp:
            resp.raise_for_status()
            data = await resp.json()
        return data.get("uuid", conv_uuid)

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------

    async def _send_message(
        self,
        prompt: str,
        headers: dict[str, str],
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        async with aiohttp.ClientSession() as session:
            org_id = await self._ensure_org_id(session, headers)
            conv_id = await self._create_conversation(session, headers, org_id)

            url = (
                f"{self._get_api_url()}/organizations/{org_id}"
                f"/chat_conversations/{conv_id}/completion"
            )
            body = {
                "prompt": prompt,
                "parent_message_uuid": "00000000-0000-4000-8000-000000000000",
                "model": self.model_name,
                "timezone": "UTC",
                "rendering_mode": "messages",
                "attachments": [],
                "files": [],
                "locale": "en-US",
                "personalized_styles": [],
                "sync_sources": [],
                "tools": [],
            }

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
        """Parse Claude SSE events.

        Claude uses:
        - content_block_delta with delta.text
        - completion with data.completion (legacy)
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

        event_type = data.get("type", "")

        if event_type == "content_block_delta":
            delta = data.get("delta", {})
            text = delta.get("text", "")
            if text:
                yield text
        elif event_type == "completion":
            text = data.get("completion", "")
            if text:
                yield text
        elif event_type == "error":
            msg = data.get("error", {}).get("message", "Claude API error")
            raise RuntimeError(msg)
