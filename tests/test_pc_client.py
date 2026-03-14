"""Tests for PC client components (importable parts only).

Note: window_tracker uses ctypes.windll which is Windows-only,
so we test the browser_tracker and executor logic separately.
"""

import sys
import os

# Add pc-client to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pc-client"))

from crawlers.browser_tracker import (
    categorize_browser_activity,
    enrich_activity_record,
    extract_tab_title,
    is_browser,
)


def test_is_browser():
    assert is_browser("chrome.exe") is True
    assert is_browser("msedge.exe") is True
    assert is_browser("firefox.exe") is True
    assert is_browser("Code.exe") is False
    assert is_browser("explorer.exe") is False


def test_extract_tab_title():
    assert extract_tab_title("GitHub - Google Chrome") == "GitHub"
    assert extract_tab_title("YouTube - Mozilla Firefox") == "YouTube"
    assert extract_tab_title("Bing - Microsoft Edge") == "Bing"
    assert extract_tab_title("VSCode - project") is None  # not a browser


def test_categorize_browser_activity():
    assert categorize_browser_activity("github.com/user/repo") == "coding"
    assert categorize_browser_activity("Gmail - Inbox") == "communication"
    assert categorize_browser_activity("YouTube - Music") == "video"
    assert categorize_browser_activity("Notion - Workspace") == "docs"
    assert categorize_browser_activity("Random Site") == "other"


def test_enrich_activity_record():
    record = {
        "window_title": "Stack Overflow - How to... - Google Chrome",
        "process_name": "chrome.exe",
        "started_at": "2026-03-14T10:00:00",
        "duration_s": 300,
    }
    enriched = enrich_activity_record(record)
    assert "browser_category" in enriched
    assert enriched["browser_category"] == "coding"
    assert "url" in enriched

    # Non-browser record should not be enriched
    record2 = {
        "window_title": "VSCode - jarvis",
        "process_name": "Code.exe",
        "started_at": "2026-03-14T10:00:00",
        "duration_s": 300,
    }
    enriched2 = enrich_activity_record(record2)
    assert "browser_category" not in enriched2


def test_claude_code_executor_not_found():
    """Test executor handles missing claude command gracefully."""
    from claude_code.executor import execute_claude_code

    result = execute_claude_code("test task", timeout=5)
    # Should return error (claude CLI likely not installed in test env)
    assert "success" in result
    if not result["success"]:
        assert result["error"] is not None
