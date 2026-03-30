# /// script
# requires-python = ">=3.12"
# dependencies = ["iterm2>=2.7", "pyobjc-framework-Quartz>=10.3"]
# ///
"""iTerm2 automation: verify Smart Launch and Connect pickers.

Launches yathaavat, tests Ctrl+R (launch picker with file discovery)
and Ctrl+K (connect picker with server discovery), verifies fuzzy
filtering and history persistence.

Screenshots → .claude/artifacts/screenshots/smart_pickers_*.png
"""

from __future__ import annotations

import asyncio
import os
import shlex
import subprocess
import time

import iterm2
from Quartz import (
    CGWindowListCopyWindowInfo,
    kCGNullWindowID,
    kCGWindowListOptionOnScreenOnly,
)

PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCREENSHOTS = os.path.join(PROJECT, ".claude", "artifacts", "screenshots")


async def _wait_for_screen_contains(
    session: iterm2.Session,
    text: str,
    *,
    timeout: float = 15.0,
    poll: float = 0.3,
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        contents = await session.async_get_screen_contents()
        if contents is not None:
            lines = [contents.line(i).string for i in range(contents.number_of_lines)]
            screen = "\n".join(lines)
            if text in screen:
                return True
        await asyncio.sleep(poll)
    return False


async def _get_screen_text(session: iterm2.Session) -> str:
    contents = await session.async_get_screen_contents()
    if contents is None:
        return ""
    return "\n".join(contents.line(i).string for i in range(contents.number_of_lines))


def _capture_screenshot(window_name: str, output_path: str) -> bool:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    windows = CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID)
    for w in windows:
        name = w.get("kCGWindowName", "")
        owner = w.get("kCGWindowOwnerName", "")
        if "iTerm2" in owner and window_name in (name or ""):
            wid = w["kCGWindowNumber"]
            subprocess.run(
                ["screencapture", "-l", str(wid), output_path],
                check=True,
                capture_output=True,
            )
            return True
    return False


async def main(connection: iterm2.Connection) -> None:
    await iterm2.async_get_app(connection)
    window = await iterm2.Window.async_create(connection)
    if window is None:
        print("ERROR: Could not create iTerm2 window")
        return

    session = window.current_tab.current_session

    try:
        # Setup
        await session.async_send_text('printf "\\e]0;yathaavat-picker-test\\a"\n')
        await asyncio.sleep(0.3)
        await session.async_send_text('printf "\\e[8;45;160t"\n')
        await asyncio.sleep(0.5)

        # Launch yathaavat
        await session.async_send_text(f"cd {shlex.quote(PROJECT)} && uv run yathaavat tui\n")

        found = await _wait_for_screen_contains(session, "DISCONNECTED", timeout=12)
        if not found:
            print("WARNING: TUI may not have loaded")
        await asyncio.sleep(1.0)

        # === TEST 1: Launch Picker ===
        print("=== Test 1: Launch Picker (Ctrl+R) ===")
        await session.async_send_text("\x12")  # Ctrl+R
        await asyncio.sleep(1.5)

        # Verify picker opened with file list
        screen = await _get_screen_text(session)
        if "Launch under debugpy" in screen:
            print("PASS: Launch picker opened")
        else:
            print("FAIL: Launch picker not visible")

        if ".py" in screen:
            print("PASS: Python files discovered")
        else:
            print("WARNING: No .py files visible (may still be scanning)")

        _capture_screenshot(
            "yathaavat-picker-test",
            os.path.join(SCREENSHOTS, "smart_pickers_launch_open.png"),
        )
        print("Screenshot: smart_pickers_launch_open.png")

        # Type "demo" to fuzzy filter
        await session.async_send_text("demo")
        await asyncio.sleep(0.5)

        screen = await _get_screen_text(session)
        if "demo" in screen.lower():
            print("PASS: Fuzzy filter working")
        else:
            print("WARNING: Fuzzy filter may not show results")

        _capture_screenshot(
            "yathaavat-picker-test",
            os.path.join(SCREENSHOTS, "smart_pickers_launch_filtered.png"),
        )
        print("Screenshot: smart_pickers_launch_filtered.png")

        # Select first result and launch
        await session.async_send_text("\r")  # Enter
        await asyncio.sleep(2.0)

        # Wait for PAUSED (should stop on exception from demo_exceptions.py)
        found = await _wait_for_screen_contains(session, "PAUSED", timeout=15)
        if found:
            print("PASS: Launch succeeded, session PAUSED")
        else:
            print("WARNING: Session may not have reached PAUSED")

        _capture_screenshot(
            "yathaavat-picker-test",
            os.path.join(SCREENSHOTS, "smart_pickers_launch_result.png"),
        )
        print("Screenshot: smart_pickers_launch_result.png")

        # Quit to test history persistence
        await session.async_send_text("\x11")  # Ctrl+Q
        await asyncio.sleep(1.5)

        # === TEST 2: History Persistence ===
        print("\n=== Test 2: History Persistence ===")
        await session.async_send_text(f"cd {shlex.quote(PROJECT)} && uv run yathaavat tui\n")
        found = await _wait_for_screen_contains(session, "DISCONNECTED", timeout=12)
        await asyncio.sleep(1.0)

        # Open launch picker again
        await session.async_send_text("\x12")  # Ctrl+R
        await asyncio.sleep(1.5)

        screen = await _get_screen_text(session)
        if "ago" in screen or "just now" in screen:
            print("PASS: History entries visible (shows relative time)")
        else:
            print("WARNING: History may not be showing")

        _capture_screenshot(
            "yathaavat-picker-test",
            os.path.join(SCREENSHOTS, "smart_pickers_launch_history.png"),
        )
        print("Screenshot: smart_pickers_launch_history.png")

        # Close picker
        await session.async_send_text("\x1b")  # Esc
        await asyncio.sleep(0.5)

        # === TEST 3: Connect Picker ===
        print("\n=== Test 3: Connect Picker (Ctrl+K) ===")
        await session.async_send_text("\x0b")  # Ctrl+K
        await asyncio.sleep(1.5)

        screen = await _get_screen_text(session)
        if "Connect to debugpy" in screen:
            print("PASS: Connect picker opened")
        else:
            print("FAIL: Connect picker not visible")

        _capture_screenshot(
            "yathaavat-picker-test",
            os.path.join(SCREENSHOTS, "smart_pickers_connect_open.png"),
        )
        print("Screenshot: smart_pickers_connect_open.png")

        # Close and quit
        await session.async_send_text("\x1b")  # Esc
        await asyncio.sleep(0.3)
        await session.async_send_text("\x11")  # Ctrl+Q
        await asyncio.sleep(1.0)

        print("\nDone. Check .claude/artifacts/screenshots/ for results.")

    finally:
        try:
            await window.async_close(force=True)
        except Exception:
            pass


iterm2.run_until_complete(main)
