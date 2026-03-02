# -*- coding: utf-8 -*-
"""API routes for Zero-Token web provider credential management."""

from __future__ import annotations

import asyncio
import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Path
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ...providers.web_models import WebCredential
from ...providers.web_registry import WEB_PROVIDERS, get_web_provider_meta
from ...providers.web_store import (
    delete_web_credential,
    get_web_credential,
    is_credential_valid,
    load_web_credentials,
    save_web_credential,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/zero-token", tags=["zero-token"])


# -- Response models --


class WebProviderInfo(BaseModel):
    id: str
    name: str
    login_url: str = ""
    models: list[dict] = Field(default_factory=list)
    status: str = "not_configured"
    captured_at: Optional[str] = None


class ChromeStartResponse(BaseModel):
    success: bool
    pid: Optional[int] = None
    message: str = ""


class CredentialStatusResponse(BaseModel):
    provider_id: str
    status: str
    captured_at: Optional[str] = None
    has_cookie: bool = False
    has_bearer: bool = False
    has_session_key: bool = False


# -- Endpoints --


@router.get(
    "/providers",
    response_model=List[WebProviderInfo],
    summary="List all web providers with credential status",
)
async def list_web_providers() -> List[WebProviderInfo]:
    creds = load_web_credentials()
    result = []
    for pid, defn in WEB_PROVIDERS.items():
        meta = get_web_provider_meta(pid)
        cred = creds.get(pid)
        if cred is None:
            status = "not_configured"
        elif is_credential_valid(cred):
            status = "active"
        else:
            status = "expired"
        result.append(
            WebProviderInfo(
                id=pid,
                name=defn.name,
                login_url=meta.get("login_url", ""),
                models=[m.model_dump() for m in defn.models],
                status=status,
                captured_at=cred.captured_at if cred else None,
            ),
        )
    return result


@router.post(
    "/chrome/start",
    response_model=ChromeStartResponse,
    summary="Start Chrome in CDP debug mode",
)
async def start_chrome(port: int = 9222) -> ChromeStartResponse:
    try:
        from ...providers.web_capture import launch_chrome_debug

        proc = launch_chrome_debug(port=port)
        if proc is None:
            return ChromeStartResponse(
                success=False,
                message="Failed to launch Chrome",
            )
        return ChromeStartResponse(
            success=True,
            pid=proc.pid,
            message=f"Chrome started on port {port}",
        )
    except Exception as exc:
        return ChromeStartResponse(success=False, message=str(exc))


@router.post(
    "/login/{provider_id}",
    summary="Capture credentials for a web provider (SSE progress)",
)
async def login_provider(
    provider_id: str = Path(...),
    port: int = 9222,
    timeout: int = 300,
) -> StreamingResponse:
    if provider_id not in WEB_PROVIDERS:
        raise HTTPException(
            404,
            detail=f"Unknown web provider: {provider_id}",
        )

    async def _stream():
        from ...providers.web_capture import capture_credentials, connect_cdp

        yield f"data: {{\"status\": \"connecting\", \"provider\": \"{provider_id}\"}}\n\n"

        try:
            browser, context = await connect_cdp(port=port)
        except Exception as exc:
            yield f"data: {{\"status\": \"error\", \"message\": \"CDP connection failed: {exc}\"}}\n\n"
            return

        try:
            yield f"data: {{\"status\": \"capturing\", \"provider\": \"{provider_id}\"}}\n\n"
            cred = await capture_credentials(
                provider_id,
                context,
                timeout=timeout,
            )
            save_web_credential(provider_id, cred)
            yield f"data: {{\"status\": \"success\", \"provider\": \"{provider_id}\"}}\n\n"
        except TimeoutError:
            yield f"data: {{\"status\": \"timeout\", \"provider\": \"{provider_id}\"}}\n\n"
        except Exception as exc:
            yield f"data: {{\"status\": \"error\", \"message\": \"{exc}\"}}\n\n"
        finally:
            await browser.close()

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
    )


@router.get(
    "/credentials/{provider_id}",
    response_model=CredentialStatusResponse,
    summary="Query credential status",
)
async def get_credential_status(
    provider_id: str = Path(...),
) -> CredentialStatusResponse:
    if provider_id not in WEB_PROVIDERS:
        raise HTTPException(
            404,
            detail=f"Unknown web provider: {provider_id}",
        )
    cred = get_web_credential(provider_id)
    if cred is None:
        return CredentialStatusResponse(
            provider_id=provider_id,
            status="not_configured",
        )
    return CredentialStatusResponse(
        provider_id=provider_id,
        status="active" if is_credential_valid(cred) else "expired",
        captured_at=cred.captured_at,
        has_cookie=bool(cred.cookie),
        has_bearer=bool(cred.bearer),
        has_session_key=bool(cred.session_key),
    )


@router.delete(
    "/credentials/{provider_id}",
    summary="Delete a stored credential",
)
async def delete_credential(
    provider_id: str = Path(...),
) -> dict:
    if provider_id not in WEB_PROVIDERS:
        raise HTTPException(
            404,
            detail=f"Unknown web provider: {provider_id}",
        )
    cred = get_web_credential(provider_id)
    if cred is None:
        raise HTTPException(
            404,
            detail=f"No credential found for '{provider_id}'",
        )
    delete_web_credential(provider_id)
    return {"message": f"Credential for '{provider_id}' deleted"}


@router.post(
    "/refresh/{provider_id}",
    summary="Refresh an expired credential",
)
async def refresh_credential(
    provider_id: str = Path(...),
    port: int = 9222,
    timeout: int = 300,
) -> StreamingResponse:
    if provider_id not in WEB_PROVIDERS:
        raise HTTPException(
            404,
            detail=f"Unknown web provider: {provider_id}",
        )
    # Reuse the login flow
    return await login_provider(provider_id, port, timeout)
