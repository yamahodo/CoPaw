# -*- coding: utf-8 -*-
"""CRUD for web credentials stored in providers.json."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from .web_models import WebCredential

# Reuse the same JSON path as the main provider store.
_PROVIDERS_DIR = Path(__file__).resolve().parent
_PROVIDERS_JSON = _PROVIDERS_DIR / "providers.json"


def _read_raw() -> dict:
    """Read providers.json and return the raw dict."""
    if not _PROVIDERS_JSON.is_file():
        return {}
    try:
        with open(_PROVIDERS_JSON, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, ValueError):
        return {}


def _write_raw(raw: dict) -> None:
    """Write the raw dict back to providers.json."""
    _PROVIDERS_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(_PROVIDERS_JSON, "w", encoding="utf-8") as fh:
        json.dump(raw, fh, indent=2, ensure_ascii=False)


def load_web_credentials() -> Dict[str, WebCredential]:
    """Load all web credentials from providers.json."""
    raw = _read_raw()
    creds: Dict[str, WebCredential] = {}
    for pid, data in raw.get("web_credentials", {}).items():
        if isinstance(data, dict):
            try:
                creds[pid] = WebCredential.model_validate(
                    {**data, "provider_id": pid},
                )
            except Exception:
                continue
    return creds


def save_web_credential(
    provider_id: str,
    credential: WebCredential,
) -> None:
    """Save a single web credential into providers.json."""
    raw = _read_raw()
    wc = raw.setdefault("web_credentials", {})
    wc[provider_id] = credential.model_dump(mode="json", exclude={"provider_id"})
    _write_raw(raw)


def get_web_credential(provider_id: str) -> Optional[WebCredential]:
    """Retrieve a single web credential, or None."""
    creds = load_web_credentials()
    return creds.get(provider_id)


def delete_web_credential(provider_id: str) -> None:
    """Remove a web credential from providers.json."""
    raw = _read_raw()
    wc = raw.get("web_credentials", {})
    if provider_id in wc:
        del wc[provider_id]
        _write_raw(raw)


def is_credential_valid(
    cred: WebCredential,
    max_age_hours: int = 24,
) -> bool:
    """Check whether a credential has expired based on captured_at."""
    if not cred.captured_at:
        return False
    try:
        captured = datetime.fromisoformat(cred.captured_at)
        if captured.tzinfo is None:
            captured = captured.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return (now - captured).total_seconds() < max_age_hours * 3600
    except (ValueError, TypeError):
        return False
