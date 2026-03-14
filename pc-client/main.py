"""PC Client entry point - starts trackers, voice, sync, and WebSocket connection.

Run: python pc-client/main.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys

# Add pc-client/ to path for sub-package imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config.settings import settings
from crawlers.browser_tracker import enrich_activity_record
from crawlers.file_tracker import FileTracker
from crawlers.screen_reader import ScreenReader
from crawlers.window_tracker import WindowTracker
from sync.server_sync import ServerSync

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("pc-client")


async def _sync_loop(
    window_tracker: WindowTracker,
    file_tracker: FileTracker,
    screen_reader: ScreenReader,
    server_sync: ServerSync,
) -> None:
    """Periodically drain tracker buffers and push to server."""
    while True:
        await asyncio.sleep(settings.sync_interval)
        try:
            # Drain window tracking buffer
            activities = window_tracker.drain_buffer()
            activities = [enrich_activity_record(a) for a in activities]
            if activities:
                await server_sync.push_pc_activity(activities)

            # Drain screen text buffer
            screen_texts = screen_reader.drain_buffer()
            if screen_texts:
                await server_sync.push_screen_texts(screen_texts)

            # Drain file events (log only for now)
            file_events = file_tracker.drain_buffer()
            if file_events:
                logger.info("File events: %d changes detected", len(file_events))
        except Exception:
            logger.exception("Sync loop error")


async def _websocket_loop(server_sync: ServerSync) -> None:
    """Maintain WebSocket connection with server for bidirectional comms."""
    try:
        import websockets
    except ImportError:
        logger.warning("websockets not installed - WebSocket connection disabled. "
                       "Install: pip install websockets")
        return

    while True:
        try:
            async with websockets.connect(settings.ws_url) as ws:
                logger.info("WebSocket connected to %s", settings.ws_url)

                # Send periodic pings and handle server messages
                async for message in ws:
                    data = json.loads(message)
                    msg_type = data.get("type", "")

                    if msg_type == "pong":
                        pass
                    elif msg_type == "claude_code_request":
                        # Execute Claude Code locally
                        asyncio.create_task(_handle_claude_code(ws, data))
                    else:
                        logger.info("Server message: %s", msg_type)

        except Exception:
            logger.warning("WebSocket disconnected, reconnecting in 10s...")
            await asyncio.sleep(10)


async def _handle_claude_code(ws, request: dict) -> None:
    """Handle a Claude Code execution request from server."""
    from claude_code.executor import execute_claude_code

    request_id = request.get("request_id", "")
    task = request.get("task", "")
    working_dir = request.get("working_dir")

    logger.info("Executing Claude Code task: %s", task[:80])

    # Run in executor (blocking subprocess)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: execute_claude_code(task, working_dir=working_dir, timeout=settings.claude_code_timeout),
    )

    # Send result back to server
    await ws.send(json.dumps({
        "type": "claude_code_result",
        "request_id": request_id,
        **result,
    }))
    logger.info("Claude Code result sent (success=%s)", result.get("success"))


async def _keyboard_trigger_loop(voice_session) -> None:
    """Listen for keyboard shortcut to trigger voice (Ctrl+Shift+J).

    Simple stdin-based fallback when pyaudio/porcupine not available.
    """
    logger.info("Press Enter to trigger voice input (or type a command)")

    loop = asyncio.get_event_loop()
    while True:
        try:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            line = line.strip()
            if not line:
                # Enter pressed = trigger voice
                if voice_session:
                    await voice_session.start_session()
            else:
                # Text typed = send as command
                from sync.server_sync import ServerSync
                # This would need the server_sync instance
                logger.info("Text command: %s", line)
        except EOFError:
            break


async def main() -> None:
    logger.info("J.A.R.V.I.S PC Client starting...")

    # Initialize components
    server_sync = ServerSync(settings.server_url, settings.sync_interval)
    await server_sync.start()

    # Check server health
    healthy = await server_sync.check_health()
    if healthy:
        logger.info("Server connection OK: %s", settings.server_url)
    else:
        logger.warning("Server not reachable: %s (will retry on sync)", settings.server_url)

    # Start window tracker
    window_tracker = WindowTracker(
        interval=settings.window_track_interval,
        idle_threshold=settings.idle_threshold,
    )
    window_tracker.start()

    # Start file tracker
    file_tracker = FileTracker(directories=settings.watch_directories)
    file_tracker.start()

    # Start screen reader
    screen_reader = ScreenReader(
        interval=settings.screen_read_interval,
        exclude_apps=settings.screen_exclude_apps,
    )
    screen_reader.start()

    # Voice session (optional)
    voice_session = None
    try:
        from voice.session import VoiceSession
        voice_session = VoiceSession(
            server_sync=server_sync,
            deepgram_api_key=settings.deepgram_api_key,
        )

        from voice.wakeword import WakeWordDetector
        wakeword = WakeWordDetector(
            access_key=settings.picovoice_access_key,
            on_detected=lambda: asyncio.run_coroutine_threadsafe(
                voice_session.start_session(),
                asyncio.get_event_loop(),
            ),
        )
        wakeword.start()
    except Exception:
        logger.info("Voice components not fully available - text mode only")

    logger.info("PC Client running. Press Ctrl+C to stop.")

    try:
        await asyncio.gather(
            _sync_loop(window_tracker, file_tracker, screen_reader, server_sync),
            _websocket_loop(server_sync),
        )
    except asyncio.CancelledError:
        pass
    finally:
        logger.info("Shutting down...")
        window_tracker.stop()
        file_tracker.stop()
        screen_reader.stop()
        await server_sync.stop()
        logger.info("PC Client stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
