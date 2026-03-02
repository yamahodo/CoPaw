# -*- coding: utf-8 -*-
"""DeepSeek web chat model -- browser-authenticated access to chat.deepseek.com."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from typing import Any, AsyncGenerator

import aiohttp

from ..web_models import WebCredential
from .base import WebChatModelBase

logger = logging.getLogger(__name__)


class DeepSeekWebChatModel(WebChatModelBase):
    """Chat model using the DeepSeek web interface.

    Handles:
    - PoW (Proof-of-Work) challenge solving (sha256 nonce brute force)
    - Session creation
    - SSE streaming with reasoning_content support
    """

    def __init__(
        self,
        model_name: str,
        credential: WebCredential,
        stream: bool = True,
    ) -> None:
        super().__init__(model_name, credential, stream)
        self._session_id: str | None = None

    def _get_api_url(self) -> str:
        return "https://chat.deepseek.com"

    # ------------------------------------------------------------------
    # PoW challenge
    # ------------------------------------------------------------------

    async def _create_pow_challenge(
        self,
        session: aiohttp.ClientSession,
        headers: dict[str, str],
        target_path: str,
    ) -> dict:
        """Request and return a PoW challenge from DeepSeek."""
        url = f"{self._get_api_url()}/api/v0/chat/create_pow_challenge"
        async with session.post(
            url,
            headers=headers,
            json={"target_path": target_path},
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()

        challenge = (
            data.get("data", {}).get("biz_data", {}).get("challenge")
            or data.get("data", {}).get("challenge")
            or data.get("challenge")
        )
        if not challenge:
            raise RuntimeError("PoW challenge missing in response")
        return challenge

    @staticmethod
    def _solve_pow(challenge: dict) -> int:
        """Brute-force solve a sha256 PoW challenge, returning the nonce."""
        algorithm = challenge.get("algorithm", "sha256")
        target = challenge.get("challenge", "")
        salt = challenge.get("salt", "")
        difficulty = challenge.get("difficulty", 0)

        if algorithm != "sha256":
            raise ValueError(f"Unsupported PoW algorithm: {algorithm}")

        target_difficulty = (
            int.bit_length(difficulty) if difficulty > 1000 else difficulty
        )

        nonce = 0
        while nonce < 2_000_000:
            input_str = f"{salt}{target}{nonce}"
            h = hashlib.sha256(input_str.encode()).hexdigest()
            zero_bits = 0
            for ch in h:
                val = int(ch, 16)
                if val == 0:
                    zero_bits += 4
                else:
                    zero_bits += (4 - val.bit_length())
                    break
            if zero_bits >= target_difficulty:
                return nonce
            nonce += 1

        raise RuntimeError("SHA256 PoW timeout (>2M iterations)")

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    async def _ensure_session(
        self,
        session: aiohttp.ClientSession,
        headers: dict[str, str],
    ) -> str:
        """Create a chat session if one doesn't exist yet."""
        if self._session_id:
            return self._session_id

        url = f"{self._get_api_url()}/api/v0/chat_session/create"
        async with session.post(url, headers=headers, json={}) as resp:
            resp.raise_for_status()
            data = await resp.json()

        session_id = (
            data.get("data", {}).get("biz_data", {}).get("id")
            or data.get("data", {}).get("biz_data", {}).get("chat_session_id")
            or data.get("data", {}).get("id")
            or ""
        )
        if not session_id:
            raise RuntimeError("Failed to create DeepSeek chat session")

        self._session_id = str(session_id)
        logger.info("DeepSeek session created: %s", self._session_id)
        return self._session_id

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------

    async def _send_message(
        self,
        prompt: str,
        headers: dict[str, str],
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        target_path = "/api/v0/chat/completion"
        url = f"{self._get_api_url()}{target_path}"

        async with aiohttp.ClientSession() as session:
            sid = await self._ensure_session(session, headers)

            # Solve PoW
            challenge = await self._create_pow_challenge(
                session, headers, target_path
            )
            nonce = self._solve_pow(challenge)
            pow_payload = {**challenge, "answer": nonce, "target_path": target_path}
            pow_response = base64.b64encode(
                json.dumps(pow_payload).encode()
            ).decode()

            send_headers = {
                **headers,
                "x-ds-pow-response": pow_response,
            }

            body = {
                "chat_session_id": sid,
                "parent_message_id": None,
                "prompt": prompt,
                "ref_file_ids": [],
                "search_enabled": False,
                "thinking_enabled": True,
            }

            async with session.post(
                url, headers=send_headers, json=body
            ) as resp:
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

                # Flush remaining buffer
                if buffer.strip():
                    for text in self._parse_sse_line(buffer.strip()):
                        yield text

    def _parse_sse_line(self, line: str):
        """Parse a single SSE line and yield text deltas."""
        if not line.startswith("data:"):
            return
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            return

        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return

        # DeepSeek uses multiple SSE formats:
        # 1. Path-based: {"p":"...", "v":"..."}
        # 2. Standard choices: {"choices":[{"delta":{"content":"..."}}]}
        # 3. Fragments: {"v":{"response":{"fragments":[...]}}}

        # Path-based reasoning
        if isinstance(data.get("v"), str):
            p = data.get("p", "")
            if "reasoning" in p or data.get("type") == "thinking":
                yield data["v"]
                return
            if not p or "content" in p or "choices" in p:
                # Filter junk tokens
                v = data["v"]
                if v not in ("<\u00a6end\u2581of\u2581thinking\u00a6>", "<|endoftext|>"):
                    yield v
                return

        # Standard OpenAI-like choices
        choice = (data.get("choices") or [{}])[0] if "choices" in data else None
        if choice:
            delta = choice.get("delta", {})
            if delta.get("reasoning_content"):
                yield delta["reasoning_content"]
            if delta.get("content"):
                yield delta["content"]
