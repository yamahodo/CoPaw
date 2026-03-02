# -*- coding: utf-8 -*-
"""Web chat models -- browser-authenticated ChatModelBase implementations."""

from .base import WebChatModelBase
from .chatgpt_web import ChatGPTWebChatModel
from .claude_web import ClaudeWebChatModel
from .deepseek_web import DeepSeekWebChatModel
from .doubao_web import DoubaoWebChatModel
from .gemini_web import GeminiWebChatModel
from .glm_web import GLMWebChatModel
from .grok_web import GrokWebChatModel
from .kimi_web import KimiWebChatModel
from .qwen_web import QwenWebChatModel

__all__ = [
    "WebChatModelBase",
    "ChatGPTWebChatModel",
    "ClaudeWebChatModel",
    "DeepSeekWebChatModel",
    "DoubaoWebChatModel",
    "GeminiWebChatModel",
    "GLMWebChatModel",
    "GrokWebChatModel",
    "KimiWebChatModel",
    "QwenWebChatModel",
]
