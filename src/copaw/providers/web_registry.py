# -*- coding: utf-8 -*-
"""Web provider definitions for Zero-Token browser-based authentication."""

from __future__ import annotations

from typing import Dict, List

from .models import ModelInfo, ProviderDefinition


# -- Web provider metadata (not stored on ProviderDefinition itself) --

WEB_PROVIDER_META: Dict[str, dict] = {
    "deepseek-web": {
        "login_url": "https://chat.deepseek.com",
        "auth_domains": ["chat.deepseek.com"],
    },
    "claude-web": {
        "login_url": "https://claude.ai",
        "auth_domains": ["claude.ai"],
    },
    "chatgpt-web": {
        "login_url": "https://chatgpt.com",
        "auth_domains": ["chatgpt.com", "chat.openai.com"],
    },
    "qwen-web": {
        "login_url": "https://chat.qwen.ai",
        "auth_domains": ["chat.qwen.ai"],
    },
    "kimi-web": {
        "login_url": "https://kimi.moonshot.cn",
        "auth_domains": ["kimi.moonshot.cn"],
    },
    "doubao-web": {
        "login_url": "https://www.doubao.com/chat",
        "auth_domains": ["www.doubao.com"],
    },
    "gemini-web": {
        "login_url": "https://gemini.google.com",
        "auth_domains": ["gemini.google.com"],
    },
    "grok-web": {
        "login_url": "https://grok.com",
        "auth_domains": ["grok.com", "api.x.ai"],
    },
    "glm-web": {
        "login_url": "https://chatglm.cn",
        "auth_domains": ["chatglm.cn"],
    },
}

# -- Model lists per web provider --

DEEPSEEK_WEB_MODELS: List[ModelInfo] = [
    ModelInfo(id="deepseek-chat", name="DeepSeek Chat"),
    ModelInfo(id="deepseek-reasoner", name="DeepSeek Reasoner"),
]

CLAUDE_WEB_MODELS: List[ModelInfo] = [
    ModelInfo(id="claude-sonnet-4-5", name="Claude Sonnet 4.5"),
    ModelInfo(id="claude-opus-4", name="Claude Opus 4"),
]

CHATGPT_WEB_MODELS: List[ModelInfo] = [
    ModelInfo(id="gpt-4o", name="GPT-4o"),
    ModelInfo(id="o1", name="o1"),
]

QWEN_WEB_MODELS: List[ModelInfo] = [
    ModelInfo(id="qwen-max-web", name="Qwen Max (Web)"),
]

KIMI_WEB_MODELS: List[ModelInfo] = [
    ModelInfo(id="kimi-web", name="Kimi (Web)"),
]

DOUBAO_WEB_MODELS: List[ModelInfo] = [
    ModelInfo(id="doubao-web", name="豆包 (Web)"),
]

GEMINI_WEB_MODELS: List[ModelInfo] = [
    ModelInfo(id="gemini-2.5-pro-web", name="Gemini 2.5 Pro (Web)"),
]

GROK_WEB_MODELS: List[ModelInfo] = [
    ModelInfo(id="grok-3-web", name="Grok 3 (Web)"),
]

GLM_WEB_MODELS: List[ModelInfo] = [
    ModelInfo(id="glm-4-web", name="GLM-4 (Web)"),
]

# -- Provider definitions --

WEB_PROVIDERS: Dict[str, ProviderDefinition] = {
    "deepseek-web": ProviderDefinition(
        id="deepseek-web",
        name="DeepSeek (Web)",
        models=DEEPSEEK_WEB_MODELS,
        is_web=True,
        chat_model="DeepSeekWebChatModel",
    ),
    "claude-web": ProviderDefinition(
        id="claude-web",
        name="Claude (Web)",
        models=CLAUDE_WEB_MODELS,
        is_web=True,
        chat_model="ClaudeWebChatModel",
    ),
    "chatgpt-web": ProviderDefinition(
        id="chatgpt-web",
        name="ChatGPT (Web)",
        models=CHATGPT_WEB_MODELS,
        is_web=True,
        chat_model="ChatGPTWebChatModel",
    ),
    "qwen-web": ProviderDefinition(
        id="qwen-web",
        name="Qwen (Web)",
        models=QWEN_WEB_MODELS,
        is_web=True,
        chat_model="QwenWebChatModel",
    ),
    "kimi-web": ProviderDefinition(
        id="kimi-web",
        name="Kimi (Web)",
        models=KIMI_WEB_MODELS,
        is_web=True,
        chat_model="KimiWebChatModel",
    ),
    "doubao-web": ProviderDefinition(
        id="doubao-web",
        name="豆包 (Web)",
        models=DOUBAO_WEB_MODELS,
        is_web=True,
        chat_model="DoubaoWebChatModel",
    ),
    "gemini-web": ProviderDefinition(
        id="gemini-web",
        name="Gemini (Web)",
        models=GEMINI_WEB_MODELS,
        is_web=True,
        chat_model="GeminiWebChatModel",
    ),
    "grok-web": ProviderDefinition(
        id="grok-web",
        name="Grok (Web)",
        models=GROK_WEB_MODELS,
        is_web=True,
        chat_model="GrokWebChatModel",
    ),
    "glm-web": ProviderDefinition(
        id="glm-web",
        name="GLM (Web)",
        models=GLM_WEB_MODELS,
        is_web=True,
        chat_model="GLMWebChatModel",
    ),
}


def sync_web_providers(providers: dict) -> None:
    """Merge web provider definitions into the main PROVIDERS dict."""
    for pid, defn in WEB_PROVIDERS.items():
        providers[pid] = defn


def get_web_provider_meta(provider_id: str) -> dict:
    """Return login_url and auth_domains for a web provider."""
    return WEB_PROVIDER_META.get(provider_id, {})


def list_web_provider_ids() -> list[str]:
    """Return all web provider IDs."""
    return list(WEB_PROVIDERS.keys())
