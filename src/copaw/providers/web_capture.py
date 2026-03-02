# -*- coding: utf-8 -*-
"""Browser credential capture engine using Playwright CDP.

Connects to a Chrome instance via the Chrome DevTools Protocol,
navigates to provider login pages, and intercepts authentication
tokens/cookies as the user logs in.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from playwright.async_api import BrowserContext, Page, async_playwright

from .web_models import WebCredential
from .web_registry import WEB_PROVIDER_META

logger = logging.getLogger(__name__)

CHROME_PROFILE_DIR = Path.home() / ".copaw" / "chrome-profile"
DEFAULT_CDP_PORT = 9222
DEFAULT_TIMEOUT = 300  # 5 minutes
POLL_INTERVAL = 2  # seconds


# ---------------------------------------------------------------------------
# Chrome launch / CDP connect helpers
# ---------------------------------------------------------------------------

def _find_chrome_binary() -> str:
    """Locate the Chrome/Chromium binary on the system."""
    candidates = [
        "google-chrome",
        "google-chrome-stable",
        "chromium-browser",
        "chromium",
    ]
    if sys.platform == "darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        ] + candidates
    elif sys.platform == "win32":
        for env_var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            base = os.environ.get(env_var, "")
            if base:
                candidates.append(
                    os.path.join(base, "Google", "Chrome", "Application", "chrome.exe")
                )

    for c in candidates:
        found = shutil.which(c) if not os.path.isabs(c) else (c if os.path.isfile(c) else None)
        if found:
            return found
    raise FileNotFoundError("Could not find Chrome or Chromium binary on this system")


def launch_chrome_debug(port: int = DEFAULT_CDP_PORT) -> subprocess.Popen:
    """Launch Chrome with ``--remote-debugging-port`` for CDP attachment.

    Uses ``~/.copaw/chrome-profile`` as the user-data directory so that
    login sessions persist across invocations.
    """
    chrome_bin = _find_chrome_binary()
    CHROME_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    args = [
        chrome_bin,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={CHROME_PROFILE_DIR}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    logger.info("Launching Chrome: %s", " ".join(args))
    proc = subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return proc


async def connect_cdp(port: int = DEFAULT_CDP_PORT):
    """Connect Playwright to an existing Chrome CDP session.

    Returns ``(playwright_instance, browser, context, page)``.
    The caller is responsible for calling ``await pw.stop()`` when done.
    """
    pw = await async_playwright().start()
    cdp_url = f"http://127.0.0.1:{port}"
    browser = await pw.chromium.connect_over_cdp(cdp_url)
    context = browser.contexts[0] if browser.contexts else await browser.new_context()
    page = context.pages[0] if context.pages else await context.new_page()
    return pw, browser, context, page


# ---------------------------------------------------------------------------
# Generic dispatcher
# ---------------------------------------------------------------------------

_CAPTURE_DISPATCH: Dict[str, Callable] = {}  # populated at module bottom


async def capture_credentials(
    provider_id: str,
    context: BrowserContext,
    timeout: int = DEFAULT_TIMEOUT,
    on_progress: Optional[Callable[[str], Any]] = None,
) -> WebCredential:
    """Capture credentials for *provider_id* via browser interception.

    *context* must be a live Playwright ``BrowserContext`` (from
    :func:`connect_cdp` or similar).  The function dispatches to a
    per-platform helper that performs request interception and cookie
    polling.
    """
    fn = _CAPTURE_DISPATCH.get(provider_id)
    if fn is None:
        raise ValueError(
            f"Unsupported web provider: {provider_id}. "
            f"Supported: {sorted(_CAPTURE_DISPATCH)}"
        )
    return await fn(context, timeout, on_progress)


# ---------------------------------------------------------------------------
# Helpers shared by per-platform functions
# ---------------------------------------------------------------------------

def _progress(on_progress: Optional[Callable[[str], Any]], msg: str) -> None:
    if on_progress is not None:
        on_progress(msg)
    else:
        logger.info(msg)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _cookies_as_string(
    context: BrowserContext,
    urls: list[str],
) -> tuple[str, list]:
    """Fetch cookies for *urls* and return ``(cookie_string, raw_cookies)``."""
    cookies = await context.cookies(urls)
    cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
    return cookie_str, cookies


async def _get_user_agent(page: Page) -> str:
    return await page.evaluate("() => navigator.userAgent")


# ---------------------------------------------------------------------------
# Per-platform capture functions
# ---------------------------------------------------------------------------

async def _capture_deepseek(
    context: BrowserContext,
    timeout: int,
    on_progress: Optional[Callable[[str], Any]],
) -> WebCredential:
    """DeepSeek: Bearer token from ``/api/v0/`` requests + cookies."""
    meta = WEB_PROVIDER_META["deepseek-web"]
    page = context.pages[0] if context.pages else await context.new_page()
    await page.goto(meta["login_url"])
    user_agent = await _get_user_agent(page)
    _progress(on_progress, "Please login to DeepSeek in the browser window...")

    captured_bearer: Optional[str] = None
    result_future: asyncio.Future[WebCredential] = asyncio.get_event_loop().create_future()

    async def try_resolve() -> None:
        nonlocal captured_bearer
        if result_future.done():
            return
        if not captured_bearer:
            return
        cookie_str, cookies = await _cookies_as_string(
            context,
            ["https://chat.deepseek.com", "https://deepseek.com"],
        )
        if not cookies:
            return
        has_device_id = "d_id=" in cookie_str
        has_session_id = "ds_session_id=" in cookie_str
        has_session_info = "HWSID=" in cookie_str or "uuid=" in cookie_str
        if has_device_id or has_session_id or has_session_info or len(cookies) > 3:
            logger.info("[DeepSeek] Credentials captured (d_id=%s, ds_session_id=%s)",
                        has_device_id, has_session_id)
            result_future.set_result(WebCredential(
                provider_id="deepseek-web",
                cookie=cookie_str,
                bearer=captured_bearer,
                user_agent=user_agent,
                captured_at=_now_iso(),
            ))

    async def on_request(request) -> None:
        nonlocal captured_bearer
        url = request.url
        if "/api/v0/" in url:
            auth = request.headers.get("authorization", "")
            if auth.startswith("Bearer ") and not captured_bearer:
                logger.info("[DeepSeek] Captured Bearer token.")
                captured_bearer = auth[7:]
                await try_resolve()

    async def on_response(response) -> None:
        nonlocal captured_bearer
        url = response.url
        if "/api/v0/users/current" in url and response.ok:
            try:
                body = await response.json()
                token = body.get("data", {}).get("biz_data", {}).get("token")
                if isinstance(token, str) and token and not captured_bearer:
                    logger.info("[DeepSeek] Captured token from users/current response.")
                    captured_bearer = token
                    await try_resolve()
            except Exception:
                pass

    page.on("request", on_request)
    page.on("response", on_response)

    try:
        elapsed = 0
        while not result_future.done() and elapsed < timeout:
            await asyncio.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL
            await try_resolve()
        if not result_future.done():
            raise TimeoutError(f"DeepSeek login timed out ({timeout}s).")
        return result_future.result()
    finally:
        page.remove_listener("request", on_request)
        page.remove_listener("response", on_response)


async def _capture_claude(
    context: BrowserContext,
    timeout: int,
    on_progress: Optional[Callable[[str], Any]],
) -> WebCredential:
    """Claude: Look for ``sessionKey`` cookie (``sk-ant-sid01-*`` / ``sk-ant-sid02-*``)."""
    meta = WEB_PROVIDER_META["claude-web"]
    page = context.pages[0] if context.pages else await context.new_page()
    await page.goto(meta["login_url"] + "/")
    user_agent = await _get_user_agent(page)
    _progress(on_progress, "Please login to Claude in the browser window...")

    captured_session_key: Optional[str] = None
    result_future: asyncio.Future[WebCredential] = asyncio.get_event_loop().create_future()

    async def try_resolve() -> None:
        nonlocal captured_session_key
        if result_future.done():
            return
        cookie_str, cookies = await _cookies_as_string(
            context,
            ["https://claude.ai", "https://www.claude.ai"],
        )
        if not cookies:
            return
        # Check cookies for sessionKey
        sk_cookie = next(
            (c for c in cookies
             if c["name"] == "sessionKey"
             or c["value"].startswith("sk-ant-sid01-")
             or c["value"].startswith("sk-ant-sid02-")),
            None,
        )
        key = captured_session_key or (sk_cookie["value"] if sk_cookie else "")
        if key.startswith("sk-ant-sid01-") or key.startswith("sk-ant-sid02-"):
            logger.info("[Claude] sessionKey captured!")
            result_future.set_result(WebCredential(
                provider_id="claude-web",
                cookie=cookie_str,
                session_key=key,
                user_agent=user_agent,
                captured_at=_now_iso(),
            ))

    async def on_request(request) -> None:
        nonlocal captured_session_key
        url = request.url
        if "claude.ai" in url:
            cookie_header = request.headers.get("cookie", "")
            m = re.search(r"sessionKey=([^;]+)", cookie_header)
            if m and (m.group(1).startswith("sk-ant-sid01-")
                      or m.group(1).startswith("sk-ant-sid02-")):
                if not captured_session_key:
                    logger.info("[Claude] Captured sessionKey from request cookie.")
                    captured_session_key = m.group(1)
                await try_resolve()

    page.on("request", on_request)

    try:
        elapsed = 0
        while not result_future.done() and elapsed < timeout:
            await asyncio.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL
            await try_resolve()
        if not result_future.done():
            raise TimeoutError(f"Claude login timed out ({timeout}s).")
        return result_future.result()
    finally:
        page.remove_listener("request", on_request)


async def _capture_chatgpt(
    context: BrowserContext,
    timeout: int,
    on_progress: Optional[Callable[[str], Any]],
) -> WebCredential:
    """ChatGPT: Look for ``Authorization`` header in ``/backend-api/`` requests
    and ``__Secure-next-auth.session-token`` cookie."""
    meta = WEB_PROVIDER_META["chatgpt-web"]
    page = context.pages[0] if context.pages else await context.new_page()
    await page.goto(meta["login_url"] + "/")
    user_agent = await _get_user_agent(page)
    _progress(on_progress, "Please login to ChatGPT in the browser window...")

    captured_token: Optional[str] = None
    result_future: asyncio.Future[WebCredential] = asyncio.get_event_loop().create_future()

    async def try_resolve() -> None:
        nonlocal captured_token
        if result_future.done():
            return
        cookie_str, cookies = await _cookies_as_string(
            context,
            ["https://chatgpt.com", "https://chat.openai.com"],
        )
        if not cookies:
            return
        session_cookie = next(
            (c for c in cookies if c["name"] == "__Secure-next-auth.session-token"),
            None,
        )
        final_token = captured_token or (session_cookie["value"] if session_cookie else "")
        if final_token:
            logger.info("[ChatGPT] Access token captured!")
            result_future.set_result(WebCredential(
                provider_id="chatgpt-web",
                cookie=cookie_str,
                bearer=final_token,
                user_agent=user_agent,
                captured_at=_now_iso(),
            ))

    async def on_request(request) -> None:
        nonlocal captured_token
        url = request.url
        if "chatgpt.com" in url or "openai.com" in url:
            cookie_header = request.headers.get("cookie", "")
            m = re.search(r"__Secure-next-auth\.session-token=([^;]+)", cookie_header)
            if m and not captured_token:
                logger.info("[ChatGPT] Captured session token from request cookie.")
                captured_token = m.group(1)
                await try_resolve()
            auth = request.headers.get("authorization", "")
            if auth.startswith("Bearer ") and not captured_token:
                logger.info("[ChatGPT] Captured Bearer from Authorization header.")
                captured_token = auth[7:]
                await try_resolve()

    page.on("request", on_request)

    try:
        elapsed = 0
        while not result_future.done() and elapsed < timeout:
            await asyncio.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL
            await try_resolve()
        if not result_future.done():
            raise TimeoutError(f"ChatGPT login timed out ({timeout}s).")
        return result_future.result()
    finally:
        page.remove_listener("request", on_request)


async def _capture_qwen(
    context: BrowserContext,
    timeout: int,
    on_progress: Optional[Callable[[str], Any]],
) -> WebCredential:
    """Qwen: Look for ``Authorization`` header and session cookies."""
    meta = WEB_PROVIDER_META["qwen-web"]
    page = context.pages[0] if context.pages else await context.new_page()
    await page.goto(meta["login_url"] + "/")
    user_agent = await _get_user_agent(page)
    _progress(on_progress, "Please login to Qwen in the browser window...")

    captured_token: Optional[str] = None
    result_future: asyncio.Future[WebCredential] = asyncio.get_event_loop().create_future()

    async def try_resolve() -> None:
        nonlocal captured_token
        if result_future.done():
            return
        cookie_str, cookies = await _cookies_as_string(
            context,
            ["https://chat.qwen.ai", "https://qwen.ai"],
        )
        if not cookies:
            return
        session_cookie = next(
            (c for c in cookies
             if "session" in c["name"] or "token" in c["name"] or "auth" in c["name"]),
            None,
        )
        final_token = captured_token or (session_cookie["value"] if session_cookie else "")
        if final_token and len(cookies) > 2:
            logger.info("[Qwen] Session token captured!")
            result_future.set_result(WebCredential(
                provider_id="qwen-web",
                cookie=cookie_str,
                bearer=final_token,
                user_agent=user_agent,
                captured_at=_now_iso(),
            ))

    async def on_request(request) -> None:
        nonlocal captured_token
        url = request.url
        if "qwen.ai" in url:
            auth = request.headers.get("authorization", "")
            if auth and not captured_token:
                logger.info("[Qwen] Captured authorization token from request.")
                captured_token = auth.replace("Bearer ", "")
                await try_resolve()
            elif not captured_token:
                cookie_header = request.headers.get("cookie", "")
                m = re.search(r"(?:session|token|auth)[^=]*=([^;]+)", cookie_header, re.IGNORECASE)
                if m:
                    logger.info("[Qwen] Captured session from cookie header.")
                    captured_token = m.group(1)
                    await try_resolve()

    page.on("request", on_request)

    try:
        elapsed = 0
        while not result_future.done() and elapsed < timeout:
            await asyncio.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL
            await try_resolve()
        if not result_future.done():
            raise TimeoutError(f"Qwen login timed out ({timeout}s).")
        return result_future.result()
    finally:
        page.remove_listener("request", on_request)


async def _capture_kimi(
    context: BrowserContext,
    timeout: int,
    on_progress: Optional[Callable[[str], Any]],
) -> WebCredential:
    """Kimi: Look for ``access_token`` cookie or ``Authorization`` header in ``/api/`` requests."""
    meta = WEB_PROVIDER_META["kimi-web"]
    page = context.pages[0] if context.pages else await context.new_page()
    await page.goto(meta["login_url"], wait_until="domcontentloaded")
    user_agent = await _get_user_agent(page)
    _progress(on_progress, "Please login to Kimi in the browser window...")

    captured_token: Optional[str] = None
    result_future: asyncio.Future[WebCredential] = asyncio.get_event_loop().create_future()

    async def try_resolve() -> None:
        nonlocal captured_token
        if result_future.done():
            return
        cookie_str, cookies = await _cookies_as_string(
            context,
            ["https://kimi.moonshot.cn"],
        )
        if not cookies:
            return
        access_cookie = next(
            (c for c in cookies if c["name"] == "access_token"),
            None,
        )
        final_token = captured_token or (access_cookie["value"] if access_cookie else "")
        if final_token:
            logger.info("[Kimi] Credentials captured!")
            result_future.set_result(WebCredential(
                provider_id="kimi-web",
                cookie=cookie_str,
                bearer=final_token,
                user_agent=user_agent,
                captured_at=_now_iso(),
            ))

    async def on_request(request) -> None:
        nonlocal captured_token
        url = request.url
        if "/api/" in url and "kimi" in url:
            auth = request.headers.get("authorization", "")
            if auth.startswith("Bearer ") and not captured_token:
                logger.info("[Kimi] Captured Bearer from /api/ request.")
                captured_token = auth[7:]
                await try_resolve()

    page.on("request", on_request)

    try:
        elapsed = 0
        while not result_future.done() and elapsed < timeout:
            await asyncio.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL
            await try_resolve()
        if not result_future.done():
            raise TimeoutError(f"Kimi login timed out ({timeout}s).")
        return result_future.result()
    finally:
        page.remove_listener("request", on_request)


async def _capture_doubao(
    context: BrowserContext,
    timeout: int,
    on_progress: Optional[Callable[[str], Any]],
) -> WebCredential:
    """Doubao: Look for ``sessionid`` and ``ttwid`` cookies."""
    meta = WEB_PROVIDER_META["doubao-web"]
    page = context.pages[0] if context.pages else await context.new_page()
    await page.goto(meta["login_url"] + "/")
    user_agent = await _get_user_agent(page)
    _progress(on_progress, "Please login to Doubao in the browser window...")

    result_future: asyncio.Future[WebCredential] = asyncio.get_event_loop().create_future()

    async def try_resolve() -> None:
        if result_future.done():
            return
        cookie_str, cookies = await _cookies_as_string(
            context,
            ["https://www.doubao.com", "https://doubao.com"],
        )
        if not cookies:
            return
        sessionid_cookie = next(
            (c for c in cookies if c["name"] == "sessionid"),
            None,
        )
        if sessionid_cookie:
            ttwid_cookie = next(
                (c for c in cookies if c["name"] == "ttwid"),
                None,
            )
            logger.info("[Doubao] sessionid captured!")
            extra: Dict[str, str] = {}
            if ttwid_cookie:
                extra["ttwid"] = ttwid_cookie["value"]
            result_future.set_result(WebCredential(
                provider_id="doubao-web",
                cookie=cookie_str,
                session_key=sessionid_cookie["value"],
                user_agent=user_agent,
                captured_at=_now_iso(),
                extra=extra,
            ))

    async def on_request(request) -> None:
        url = request.url
        if "doubao.com" in url:
            cookie_header = request.headers.get("cookie", "")
            if "sessionid" in cookie_header:
                logger.info("[Doubao] Found sessionid in request cookie.")
                await try_resolve()

    page.on("request", on_request)

    try:
        elapsed = 0
        while not result_future.done() and elapsed < timeout:
            await asyncio.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL
            await try_resolve()
        if not result_future.done():
            raise TimeoutError(f"Doubao login timed out ({timeout}s).")
        return result_future.result()
    finally:
        page.remove_listener("request", on_request)


async def _capture_gemini(
    context: BrowserContext,
    timeout: int,
    on_progress: Optional[Callable[[str], Any]],
) -> WebCredential:
    """Gemini: Look for Google auth cookies (``SID``, ``__Secure-1PSID``)."""
    meta = WEB_PROVIDER_META["gemini-web"]
    page = context.pages[0] if context.pages else await context.new_page()
    await page.goto(meta["login_url"] + "/app", wait_until="domcontentloaded")
    user_agent = await _get_user_agent(page)
    _progress(on_progress, "Please login to Gemini in the browser window...")

    result_future: asyncio.Future[WebCredential] = asyncio.get_event_loop().create_future()

    async def try_resolve() -> None:
        if result_future.done():
            return
        cookie_str, cookies = await _cookies_as_string(
            context,
            ["https://gemini.google.com"],
        )
        if not cookies:
            return
        has_sid = any(c["name"] == "SID" for c in cookies)
        has_secure_psid = any(c["name"] == "__Secure-1PSID" for c in cookies)
        if has_sid or has_secure_psid:
            logger.info("[Gemini] Google auth cookies captured!")
            result_future.set_result(WebCredential(
                provider_id="gemini-web",
                cookie=cookie_str,
                user_agent=user_agent,
                captured_at=_now_iso(),
            ))

    try:
        elapsed = 0
        while not result_future.done() and elapsed < timeout:
            await asyncio.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL
            await try_resolve()
        if not result_future.done():
            raise TimeoutError(f"Gemini login timed out ({timeout}s).")
        return result_future.result()
    finally:
        pass  # no listeners to remove


async def _capture_grok(
    context: BrowserContext,
    timeout: int,
    on_progress: Optional[Callable[[str], Any]],
) -> WebCredential:
    """Grok: Look for auth cookies (``sso``, ``_ga``) and tokens."""
    meta = WEB_PROVIDER_META["grok-web"]
    page = context.pages[0] if context.pages else await context.new_page()
    await page.goto(meta["login_url"], wait_until="domcontentloaded")
    user_agent = await _get_user_agent(page)
    _progress(on_progress, "Please login to Grok in the browser window...")

    captured_token: Optional[str] = None
    result_future: asyncio.Future[WebCredential] = asyncio.get_event_loop().create_future()

    async def try_resolve() -> None:
        if result_future.done():
            return
        cookie_str, cookies = await _cookies_as_string(
            context,
            ["https://grok.com"],
        )
        if not cookies:
            return
        has_sso = any(c["name"] == "sso" for c in cookies)
        has_ga = any(c["name"] == "_ga" for c in cookies)
        if has_sso or has_ga:
            logger.info("[Grok] Auth cookies captured!")
            result_future.set_result(WebCredential(
                provider_id="grok-web",
                cookie=cookie_str,
                bearer=captured_token or "",
                user_agent=user_agent,
                captured_at=_now_iso(),
            ))

    async def on_request(request) -> None:
        nonlocal captured_token
        url = request.url
        if "grok.com" in url or "x.ai" in url:
            auth = request.headers.get("authorization", "")
            if auth.startswith("Bearer ") and not captured_token:
                logger.info("[Grok] Captured Bearer token from request.")
                captured_token = auth[7:]
                await try_resolve()

    page.on("request", on_request)

    try:
        elapsed = 0
        while not result_future.done() and elapsed < timeout:
            await asyncio.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL
            await try_resolve()
        if not result_future.done():
            raise TimeoutError(f"Grok login timed out ({timeout}s).")
        return result_future.result()
    finally:
        page.remove_listener("request", on_request)


async def _capture_glm(
    context: BrowserContext,
    timeout: int,
    on_progress: Optional[Callable[[str], Any]],
) -> WebCredential:
    """GLM (ChatGLM): Look for ``chatglm_refresh_token`` cookie."""
    meta = WEB_PROVIDER_META["glm-web"]
    page = context.pages[0] if context.pages else await context.new_page()
    await page.goto(meta["login_url"], wait_until="domcontentloaded")
    user_agent = await _get_user_agent(page)
    _progress(on_progress, "Please login to ChatGLM in the browser window...")

    result_future: asyncio.Future[WebCredential] = asyncio.get_event_loop().create_future()

    async def try_resolve() -> None:
        if result_future.done():
            return
        cookie_str, cookies = await _cookies_as_string(
            context,
            ["https://chatglm.cn"],
        )
        if not cookies:
            return
        token_cookie = next(
            (c for c in cookies if c["name"] == "chatglm_refresh_token"),
            None,
        )
        if token_cookie:
            logger.info("[GLM] chatglm_refresh_token captured!")
            result_future.set_result(WebCredential(
                provider_id="glm-web",
                cookie=cookie_str,
                session_key=token_cookie["value"],
                user_agent=user_agent,
                captured_at=_now_iso(),
            ))

    try:
        elapsed = 0
        while not result_future.done() and elapsed < timeout:
            await asyncio.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL
            await try_resolve()
        if not result_future.done():
            raise TimeoutError(f"ChatGLM login timed out ({timeout}s).")
        return result_future.result()
    finally:
        pass  # no listeners to remove


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

_CAPTURE_DISPATCH.update({
    "deepseek-web": _capture_deepseek,
    "claude-web": _capture_claude,
    "chatgpt-web": _capture_chatgpt,
    "qwen-web": _capture_qwen,
    "kimi-web": _capture_kimi,
    "doubao-web": _capture_doubao,
    "gemini-web": _capture_gemini,
    "grok-web": _capture_grok,
    "glm-web": _capture_glm,
})
