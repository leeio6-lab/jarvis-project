"""Extracts browser tab title and URL from window titles.

Browsers embed the tab title in the window title:
  Chrome:  "Tab Title - Google Chrome"
  Firefox: "Tab Title - Mozilla Firefox"
  Edge:    "Tab Title - Microsoft Edge"
  Arc:     "Tab Title - Arc"

URL extraction requires accessibility APIs or browser extensions,
so we track titles only (sufficient for activity categorization).
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_BROWSER_SUFFIXES = [
    " - Google Chrome",
    " - Mozilla Firefox",
    " - Microsoft Edge",
    " - Arc",
    " - Brave",
    " - Opera",
    " - Vivaldi",
]

_BROWSER_PROCESSES = {
    "chrome.exe", "firefox.exe", "msedge.exe", "arc.exe",
    "brave.exe", "opera.exe", "vivaldi.exe",
}


def is_browser(process_name: str) -> bool:
    return process_name.lower() in _BROWSER_PROCESSES


def extract_tab_title(window_title: str) -> str | None:
    """Extract the tab title from a browser window title."""
    for suffix in _BROWSER_SUFFIXES:
        if window_title.endswith(suffix):
            return window_title[: -len(suffix)]
    return None


def categorize_browser_activity(tab_title: str) -> str:
    """Categorize browser activity based on tab title keywords."""
    title_lower = tab_title.lower()

    categories = {
        "coding": ["github", "gitlab", "stackoverflow", "stack overflow", "codepen",
                    "jsfiddle", "leetcode", "hackerrank", "replit"],
        "communication": ["gmail", "outlook", "slack", "discord", "teams",
                          "kakao", "telegram", "whatsapp"],
        "docs": ["google docs", "google sheets", "notion", "confluence",
                 "google slides", "figma", "miro"],
        "video": ["youtube", "netflix", "twitch", "vimeo"],
        "social": ["twitter", "x.com", "facebook", "instagram", "reddit",
                   "linkedin", "threads"],
        "search": ["google", "naver", "daum", "bing"],
        "news": ["news", "bbc", "cnn", "nytimes"],
    }

    for category, keywords in categories.items():
        if any(kw in title_lower for kw in keywords):
            return category

    return "other"


def enrich_activity_record(record: dict) -> dict:
    """Add browser-specific metadata to an activity record."""
    process = record.get("process_name", "")
    title = record.get("window_title", "")

    if is_browser(process):
        tab_title = extract_tab_title(title)
        if tab_title:
            record["url"] = f"tab://{tab_title}"  # pseudo-URL from title
            record["browser_category"] = categorize_browser_activity(tab_title)

    return record
