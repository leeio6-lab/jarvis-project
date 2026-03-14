"""Unified text extraction service — auto-selects the best method per app.

    Active window detected
           |
    Is it a browser? (msedge.exe, chrome.exe, firefox.exe)
       YES --> CDP (Chrome DevTools Protocol) --> full DOM innerText
       NO  --> UIAutomation --> control tree text (SAP, Excel, KakaoTalk)

Fallback chain:
  1. CDP connection  --> 100% accurate DOM text (mail body, tables, everything)
  2. UIAutomation    --> partial text (tab titles + visible controls)
  3. Window title    --> title only (last resort)

No browser extension needed. No user setup needed. Just run pc-client.
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_BROWSER_PROCESSES = {
    "msedge.exe", "chrome.exe", "firefox.exe", "brave.exe", "vivaldi.exe",
}

# CDP ports to try — browsers sometimes expose debug on these
_CDP_PORTS = [9222, 9229, 9223]

MAX_TEXT_LENGTH = 2000

# Sensitive page detection
_SENSITIVE_URL_KEYWORDS = [
    "login", "signin", "sign-in", "auth", "oauth", "sso", "2fa",
    "banking", "bank.", "payment", "checkout",
    "kbstar", "shinhan", "woori", "hana", "ibk",
    "toss.im", "kakaopay", "naverpay",
]


def _is_sensitive_url(url: str) -> bool:
    url_lower = url.lower()
    return any(kw in url_lower for kw in _SENSITIVE_URL_KEYWORDS)


# ── CDP extraction ────────────────────────────────────────────────────

async def _find_cdp_endpoint(process_name: str, window_title: str = "") -> str | None:
    """Find the CDP WebSocket for the tab matching the active window title."""
    import httpx

    _BROWSER_SUFFIXES = [
        " - Microsoft\u200b Edge", " - Microsoft Edge",
        " - Google Chrome", " - Mozilla Firefox", " - Brave",
    ]

    for port in _CDP_PORTS:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"http://127.0.0.1:{port}/json", timeout=2.0,
                )
                if resp.status_code != 200:
                    continue
                tabs = resp.json()
                pages = [t for t in tabs if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
                if not pages:
                    continue

                # Match active tab by window title
                if window_title:
                    page_title = window_title
                    # Strip browser suffix: " - Microsoft Edge", " - 개인 - Microsoft Edge"
                    for suffix in _BROWSER_SUFFIXES:
                        idx = page_title.find(suffix)
                        if idx > 0:
                            page_title = page_title[:idx]
                            break
                    # Strip Edge multi-tab suffix: "Title 외 페이지 N개"
                    import re
                    page_title = re.sub(r"\s*외\s*페이지\s*\d+개.*$", "", page_title)
                    page_title = page_title.strip()

                    for tab in pages:
                        tab_title = tab.get("title", "")
                        if page_title and (tab_title.startswith(page_title) or page_title in tab_title):
                            return tab["webSocketDebuggerUrl"]

                # Fallback: first page tab
                return pages[0]["webSocketDebuggerUrl"]
        except Exception:
            continue
    return None


async def _extract_via_cdp(ws_url: str) -> dict[str, Any] | None:
    """Extract page text via Chrome DevTools Protocol WebSocket."""
    import websockets

    try:
        async with websockets.connect(ws_url, close_timeout=5) as ws:
            # Get page URL first
            await ws.send(json.dumps({
                "id": 1,
                "method": "Runtime.evaluate",
                "params": {"expression": "window.location.href"}
            }))
            url_resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            url = url_resp.get("result", {}).get("result", {}).get("value", "")

            # Safety: skip sensitive URLs
            if _is_sensitive_url(url):
                logger.debug("CDP: skipping sensitive URL: %s", url[:60])
                return None

            # Check for password fields
            await ws.send(json.dumps({
                "id": 2,
                "method": "Runtime.evaluate",
                "params": {"expression": "document.querySelectorAll('input[type=password]').length"}
            }))
            pw_resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            pw_count = pw_resp.get("result", {}).get("result", {}).get("value", 0)
            if pw_count and pw_count > 0:
                logger.debug("CDP: password field detected, skipping")
                return None

            # Get page title
            await ws.send(json.dumps({
                "id": 3,
                "method": "Runtime.evaluate",
                "params": {"expression": "document.title"}
            }))
            title_resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            title = title_resp.get("result", {}).get("result", {}).get("value", "")

            # Get page text (the gold)
            await ws.send(json.dumps({
                "id": 4,
                "method": "Runtime.evaluate",
                "params": {"expression": f"document.body.innerText.slice(0, {MAX_TEXT_LENGTH})"}
            }))
            text_resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            text = text_resp.get("result", {}).get("result", {}).get("value", "")

            if not text or len(text.strip()) < 10:
                return None

            # Clean whitespace
            text = text.replace("\n\n\n", "\n\n").strip()

            # Domain label
            from urllib.parse import urlparse
            hostname = urlparse(url).hostname or ""
            domain_labels = {
                "mail.worksmobile.com": "네이버 웍스",
                "mail.google.com": "Gmail",
                "calendar.google.com": "Google Calendar",
                "github.com": "GitHub",
                "notion.so": "Notion",
                "claude.ai": "Claude",
            }
            app_label = next(
                (v for k, v in domain_labels.items() if k in hostname),
                hostname,
            )

            return {
                "app_name": app_label,
                "window_title": title,
                "extracted_text": text,
                "text_length": len(text),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": "cdp",
            }

    except Exception as e:
        logger.debug("CDP extraction failed: %s", e)
        return None


# ── Unified extractor ─────────────────────────────────────────────────

async def extract_text(exclude_apps: list[str] | None = None) -> dict[str, Any] | None:
    """Extract text from active window using the best available method.

    Browser → CDP → UIAutomation fallback
    Non-browser → UIAutomation → title-only fallback
    """
    from crawlers.screen_reader import extract_active_window_text, _get_title_and_app

    # Step 1: lightweight check — what app is active?
    info = _get_title_and_app(exclude_apps=exclude_apps)
    if not info:
        return None

    title, app = info
    is_browser = app.lower() in _BROWSER_PROCESSES

    # Step 2: browser → try CDP first
    if is_browser:
        cdp_ws = await _find_cdp_endpoint(app, window_title=title)
        if cdp_ws:
            result = await _extract_via_cdp(cdp_ws)
            if result:
                logger.debug("Text extracted via CDP: %s (%d chars)",
                             result["app_name"], result["text_length"])
                return result
            # CDP connected but page was sensitive/empty — don't fall through
            # to UIAutomation for the same page
            logger.debug("CDP connected but no text (sensitive/empty)")

    # Step 3: UIAutomation (all apps, or browser fallback)
    result = extract_active_window_text(exclude_apps=exclude_apps)
    if result:
        result["source"] = "uiautomation"
        logger.debug("Text extracted via UIAutomation: %s (%d chars)",
                     result.get("app_name", "?"), result.get("text_length", 0))
        return result

    # Step 4: title-only fallback
    return {
        "app_name": app,
        "window_title": title,
        "extracted_text": title,
        "text_length": len(title),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "title_only",
    }


def extract_text_sync(exclude_apps: list[str] | None = None) -> dict[str, Any] | None:
    """Synchronous wrapper for use in threaded ScreenReader loop."""
    try:
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(extract_text(exclude_apps))
        loop.close()
        return result
    except Exception:
        logger.exception("Text extraction error")
        return None
