# -*- coding: utf-8 -*-
"""WebChatModelBase -- abstract base for browser-authenticated web chat models."""

from __future__ import annotations

import abc
import hashlib
import json
import logging
from datetime import datetime
from typing import Any, AsyncGenerator, Literal, Optional, Type

import aiohttp
from pydantic import BaseModel

from agentscope.model._model_base import ChatModelBase
from agentscope.model._model_response import ChatResponse
from agentscope.model._model_usage import ChatUsage
from agentscope.message import TextBlock, ThinkingBlock, ToolUseBlock

from ..web_models import WebCredential
from ...local_models.tag_parser import (
    extract_thinking_from_text,
    parse_tool_calls_from_text,
    text_contains_think_tag,
    text_contains_tool_call_tag,
)

logger = logging.getLogger(__name__)

_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def _json_loads_safe(s: str) -> dict:
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return {}


class WebChatModelBase(ChatModelBase, abc.ABC):
    """Abstract base class for web (browser-authenticated) chat models.

    Subclasses must implement ``_send_message`` and ``_get_api_url``.
    """

    def __init__(
        self,
        model_name: str,
        credential: WebCredential,
        stream: bool = True,
    ) -> None:
        super().__init__(model_name, stream)
        self._credential = credential

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def __call__(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: Literal["auto", "none", "required"] | str | None = None,
        structured_model: Type[BaseModel] | None = None,
        **kwargs: Any,
    ) -> ChatResponse | AsyncGenerator[ChatResponse, None]:
        start_datetime = datetime.now()

        prompt = self._format_messages_as_prompt(messages, tools)

        if self.stream and not structured_model:
            return self._stream_response(prompt, start_datetime, tools)

        # Non-streaming: collect everything at once
        accumulated = ""
        headers = self._build_headers()
        async for chunk in self._send_message(prompt, headers, **kwargs):
            accumulated += chunk

        return self._parse_full_response(
            accumulated, start_datetime, structured_model
        )

    # ------------------------------------------------------------------
    # Prompt formatting
    # ------------------------------------------------------------------

    def _format_messages_as_prompt(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> str:
        """Convert an OpenAI-format message list into a single prompt string."""
        parts: list[str] = []

        tool_system_prompt = self._build_tool_prompt(tools)
        if tool_system_prompt:
            parts.append(f"system: {tool_system_prompt}")

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if isinstance(content, list):
                # Multi-part content (text blocks, tool results, etc.)
                text_pieces: list[str] = []
                for part in content:
                    if isinstance(part, dict):
                        if part.get("type") == "text":
                            text_pieces.append(part.get("text", ""))
                        elif part.get("type") == "thinking":
                            text_pieces.append(
                                f"<think>{part.get('thinking', '')}</think>"
                            )
                        elif part.get("type") == "tool_use":
                            tc = {
                                "name": part.get("name", ""),
                                "arguments": part.get("input", {}),
                            }
                            text_pieces.append(
                                f"<tool_call>{json.dumps(tc, ensure_ascii=False)}</tool_call>"
                            )
                        elif part.get("type") == "tool_result":
                            text_pieces.append(
                                f'<tool_response id="{part.get("tool_use_id", "")}">'
                                f'{part.get("content", "")}'
                                f"</tool_response>"
                            )
                content = "\n".join(text_pieces)

            parts.append(f"{role}: {content}")

        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Tool prompt injection
    # ------------------------------------------------------------------

    @staticmethod
    def _build_tool_prompt(tools: list[dict] | None) -> str:
        """Build a system-level prompt describing available tools."""
        if not tools:
            return ""

        lines = [
            "## Tool Use Instructions",
            "You have access to the following tools. To call a tool, "
            'output: <tool_call>{"name":"tool_name", "arguments":{...}}</tool_call>',
            "",
            "### Available Tools",
        ]
        for tool in tools:
            func = tool.get("function", tool)
            name = func.get("name", "unknown")
            desc = func.get("description", "")
            params = func.get("parameters", {})
            lines.append(f"#### {name}")
            if desc:
                lines.append(desc)
            lines.append(f"Parameters: {json.dumps(params, ensure_ascii=False)}")
            lines.append("")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # HTTP header building
    # ------------------------------------------------------------------

    def _build_headers(self) -> dict[str, str]:
        """Build common HTTP headers from the stored credential."""
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "User-Agent": self._credential.user_agent or _DEFAULT_USER_AGENT,
        }
        if self._credential.cookie:
            headers["Cookie"] = self._credential.cookie
        if self._credential.bearer:
            headers["Authorization"] = f"Bearer {self._credential.bearer}"
        return headers

    # ------------------------------------------------------------------
    # SSE helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _iter_sse_lines(raw: str):
        """Yield ``data`` payloads from raw SSE text."""
        for line in raw.split("\n"):
            line = line.strip()
            if line.startswith("data:"):
                payload = line[5:].strip()
                if payload and payload != "[DONE]":
                    yield payload

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------

    async def _stream_response(
        self,
        prompt: str,
        start_datetime: datetime,
        tools: list[dict] | None = None,
    ) -> AsyncGenerator[ChatResponse, None]:
        """Drive ``_send_message`` and yield ``ChatResponse`` objects."""
        headers = self._build_headers()

        accumulated_text = ""
        accumulated_thinking = ""

        async for chunk in self._send_message(prompt, headers):
            accumulated_text += chunk

            contents: list = []
            effective_thinking = accumulated_thinking
            effective_text = accumulated_text

            # Extract <think> tags if present
            if effective_text and text_contains_think_tag(effective_text):
                parsed = extract_thinking_from_text(effective_text)
                effective_thinking = parsed.thinking
                effective_text = parsed.remaining_text
                if parsed.has_open_tag:
                    effective_text = ""

            if effective_thinking:
                contents.append(
                    ThinkingBlock(type="thinking", thinking=effective_thinking)
                )

            # Parse <tool_call> tags from text
            if effective_text and text_contains_tool_call_tag(effective_text):
                parsed_tc = parse_tool_calls_from_text(effective_text)
                display_text = parsed_tc.text_before
                if parsed_tc.text_after:
                    display_text = (
                        f"{display_text}\n{parsed_tc.text_after}".strip()
                        if display_text
                        else parsed_tc.text_after
                    )
                if display_text:
                    contents.append(TextBlock(type="text", text=display_text))
                for tc in parsed_tc.tool_calls:
                    contents.append(
                        ToolUseBlock(
                            type="tool_use",
                            id=tc.id,
                            name=tc.name,
                            input=tc.arguments,
                            raw_input=tc.raw_arguments,
                        )
                    )
            elif effective_text:
                contents.append(TextBlock(type="text", text=effective_text))

            if contents:
                elapsed = (datetime.now() - start_datetime).total_seconds()
                yield ChatResponse(
                    content=contents,
                    usage=ChatUsage(
                        input_tokens=0, output_tokens=0, time=elapsed
                    ),
                )

    # ------------------------------------------------------------------
    # Non-streaming parse
    # ------------------------------------------------------------------

    def _parse_full_response(
        self,
        text: str,
        start_datetime: datetime,
        structured_model: Type[BaseModel] | None = None,
    ) -> ChatResponse:
        """Parse fully accumulated text into a ChatResponse."""
        contents: list = []
        metadata = None

        effective_thinking = ""
        effective_text = text

        if text and text_contains_think_tag(text):
            parsed = extract_thinking_from_text(text)
            effective_thinking = parsed.thinking
            effective_text = parsed.remaining_text

        if effective_thinking:
            contents.append(
                ThinkingBlock(type="thinking", thinking=effective_thinking)
            )

        if effective_text and text_contains_tool_call_tag(effective_text):
            parsed_tc = parse_tool_calls_from_text(effective_text)
            display_text = parsed_tc.text_before
            if parsed_tc.text_after:
                display_text = (
                    f"{display_text}\n{parsed_tc.text_after}".strip()
                    if display_text
                    else parsed_tc.text_after
                )
            if display_text:
                contents.append(TextBlock(type="text", text=display_text))
                if structured_model:
                    metadata = _json_loads_safe(display_text)
            for tc in parsed_tc.tool_calls:
                contents.append(
                    ToolUseBlock(
                        type="tool_use",
                        id=tc.id,
                        name=tc.name,
                        input=tc.arguments,
                        raw_input=tc.raw_arguments,
                    )
                )
        elif effective_text:
            contents.append(TextBlock(type="text", text=effective_text))
            if structured_model:
                metadata = _json_loads_safe(effective_text)

        elapsed = (datetime.now() - start_datetime).total_seconds()
        return ChatResponse(
            content=contents,
            usage=ChatUsage(input_tokens=0, output_tokens=0, time=elapsed),
            metadata=metadata,
        )

    # ------------------------------------------------------------------
    # Abstract methods for subclasses
    # ------------------------------------------------------------------

    @abc.abstractmethod
    async def _send_message(
        self,
        prompt: str,
        headers: dict[str, str],
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        """Send *prompt* and yield text chunks.

        Subclasses handle the HTTP request, SSE parsing, and platform-specific
        details.  They should yield plain text deltas (not JSON).
        """
        ...  # pragma: no cover
        # Make this an async generator in the type system
        yield ""  # type: ignore[misc]

    @abc.abstractmethod
    def _get_api_url(self) -> str:
        """Return the base API URL for this platform."""
        ...  # pragma: no cover
