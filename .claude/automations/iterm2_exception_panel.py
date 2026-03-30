# /// script
# requires-python = ">=3.12"
# dependencies = ["iterm2>=2.7", "pyobjc-framework-Quartz>=10.3"]
# ///
"""iTerm2 automation: verify the Exception panel for yathaavat.

Launches yathaavat, uses Ctrl+R to launch a demo script that raises a ValueError,
and verifies the Exception tab auto-activates with the correct exception info.

Screenshots → .claude/artifacts/screenshots/exception_panel_*.png
"""

from __future__ import annotations

import asyncio
import os
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
        # Set window title for screenshot capture
        await session.async_send_text('printf "\\e]0;yathaavat-exc-test\\a"\n')
        await asyncio.sleep(0.3)

        # Resize window to ~1/3 desktop (160x45)
        await session.async_send_text('printf "\\e[8;45;160t"\n')
        await asyncio.sleep(0.5)

        # Navigate to project and launch yathaavat
        await session.async_send_text(f"cd {PROJECT} && uv run yathaavat tui\n")

        # Wait for TUI to load
        found = await _wait_for_screen_contains(session, "DISCONNECTED", timeout=12)
        if not found:
            print("WARNING: TUI may not have loaded")
        await asyncio.sleep(1.0)

        # Use Ctrl+R (Launch) instead of Ctrl+K (Connect)
        await session.async_send_text("\x12")  # Ctrl+R
        await asyncio.sleep(1.0)

        # Wait for Launch dialog
        found = await _wait_for_screen_contains(session, "Launch", timeout=5)
        if not found:
            print("WARNING: Launch dialog not found")

        # Enter the demo script path and submit
        await session.async_send_text("examples/demo_exceptions.py 1\r")

        # Wait for exception stop
        found = await _wait_for_screen_contains(session, "PAUSED", timeout=15)
        if found:
            print("PASS: Session entered PAUSED state")
        else:
            print("FAIL: Session did not reach PAUSED state")

        await asyncio.sleep(2.0)  # Wait for exceptionInfo to be fetched

        # Screenshot 1: Exception panel should be visible
        _capture_screenshot(
            "yathaavat-exc-test",
            os.path.join(SCREENSHOTS, "exception_panel_valueerror.png"),
        )
        print("Screenshot 1: exception_panel_valueerror.png")

        # Verify exception content
        screen = await _get_screen_text(session)
        if "ValueError" in screen:
            print("PASS: ValueError visible on screen")
        else:
            print("FAIL: ValueError not visible")
            for line in screen.splitlines()[-20:]:
                print(f"  | {line}")

        if "Exception" in screen:
            print("PASS: Exception tab visible")
        else:
            print("WARNING: Exception tab text not in screen dump")

        # Screenshot 2: Detail view
        await asyncio.sleep(0.5)
        _capture_screenshot(
            "yathaavat-exc-test",
            os.path.join(SCREENSHOTS, "exception_panel_detail.png"),
        )
        print("Screenshot 2: exception_panel_detail.png")

        # Quit yathaavat
        await session.async_send_text("\x11")  # Ctrl+Q
        await asyncio.sleep(1.0)

        print("\nDone. Check .claude/artifacts/screenshots/ for results.")

    finally:
        try:
            await window.async_close(force=True)
        except Exception:
            pass


iterm2.run_until_complete(main)
