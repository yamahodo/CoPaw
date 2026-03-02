# -*- coding: utf-8 -*-
"""Pydantic data models for web provider credentials."""

from __future__ import annotations

from typing import Dict

from pydantic import BaseModel, Field


class WebCredential(BaseModel):
    """Authentication credential captured from a browser session."""

    provider_id: str = Field(..., description="Web provider identifier")
    cookie: str = Field(default="", description="Browser cookie string")
    bearer: str = Field(default="", description="Bearer / access token")
    session_key: str = Field(
        default="",
        description="Session key (e.g. Claude sk-ant-sid01-*)",
    )
    user_agent: str = Field(default="", description="Browser User-Agent")
    captured_at: str = Field(
        default="",
        description="ISO-format datetime when the credential was captured",
    )
    extra: Dict[str, str] = Field(
        default_factory=dict,
        description="Platform-specific extra fields",
    )
