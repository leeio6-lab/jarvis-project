"""PC Client configuration."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

_CONFIG_PATH = Path(__file__).parent.parent / "config.json"


@dataclass
class PcClientSettings:
    # Server
    server_url: str = "http://localhost:8000"
    ws_url: str = "ws://localhost:8000/ws/pc-client"

    # Tracking intervals (seconds)
    window_track_interval: float = 5.0
    sync_interval: float = 60.0
    idle_threshold: float = 300.0  # 5 min no input = idle

    # File tracking
    watch_directories: list[str] = field(default_factory=lambda: [])

    # Voice
    wakeword: str = "jarvis"
    picovoice_access_key: str = ""
    deepgram_api_key: str = ""

    # Screen reader
    screen_read_interval: float = 30.0
    screen_exclude_apps: list[str] = field(default_factory=lambda: [])

    # Claude Code
    claude_code_timeout: int = 600

    @classmethod
    def load(cls) -> PcClientSettings:
        s = cls()
        if _CONFIG_PATH.exists():
            data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
            for k, v in data.items():
                if hasattr(s, k):
                    setattr(s, k, v)
        return s

    def save(self) -> None:
        _CONFIG_PATH.write_text(
            json.dumps(self.__dict__, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


settings = PcClientSettings.load()
