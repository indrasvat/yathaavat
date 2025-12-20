# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "iterm2",
#   "pyobjc",
# ]
# ///

from __future__ import annotations

import asyncio
import socket
import subprocess
import time
from pathlib import Path

import iterm2
from Quartz import (
    CGWindowListCopyWindowInfo,
    kCGNullWindowID,
    kCGWindowListOptionOnScreenOnly,
)

REPO_NAME = "indrasvat-yathaavat"


def _ensure_iterm2_running() -> None:
    running = (
        subprocess.run(["pgrep", "-x", "iTerm2"], check=False, capture_output=True).returncode == 0
    )
    if running:
        return
    subprocess.run(["open", "-a", "iTerm"], check=False)
    for _ in range(30):
        if subprocess.run(["pgrep", "-x", "iTerm2"], check=False).returncode == 0:
            return
        time.sleep(0.2)
    raise RuntimeError("iTerm2 did not start in time")


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        _host, port = s.getsockname()
        return int(port)


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in [here, *here.parents]:
        if (parent / "pyproject.toml").exists():
            return parent
    msg = f"Could not find repo root from {here}"
    raise RuntimeError(msg)


def _artifacts_dir() -> Path:
    root = _repo_root()
    out = root / ".claude" / "artifacts" / "screenshots"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _frontmost_iterm2_cgwindow_id() -> int | None:
    windows = CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID)
    for w in windows or []:
        if w.get("kCGWindowOwnerName") == "iTerm2" and w.get("kCGWindowLayer") == 0:
            win_id = w.get("kCGWindowNumber")
            if isinstance(win_id, int):
                return win_id
    return None


def _screencapture(path: Path) -> None:
    win_id = _frontmost_iterm2_cgwindow_id()
    if win_id is None:
        raise RuntimeError("Could not find iTerm2 window id for screencapture")
    subprocess.run(["screencapture", "-x", "-l", str(win_id), str(path)], check=True)


async def _screen_text(session: iterm2.Session) -> str:
    screen = await session.async_get_screen_contents()
    lines = [screen.line(i).string for i in range(screen.number_of_lines)]
    return "\n".join(lines)


async def _wait_for_screen_contains(session: iterm2.Session, needle: str, timeout_s: float) -> str:
    deadline = time.monotonic() + timeout_s
    last = ""
    while time.monotonic() < deadline:
        last = await _screen_text(session)
        if needle in last:
            return last
        await asyncio.sleep(0.25)
    msg = f"Timed out waiting for screen to contain {needle!r}"
    raise TimeoutError(msg)


async def _wait_for_screen_not_contains(
    session: iterm2.Session, needle: str, timeout_s: float
) -> str:
    deadline = time.monotonic() + timeout_s
    last = ""
    while time.monotonic() < deadline:
        last = await _screen_text(session)
        if needle not in last:
            return last
        await asyncio.sleep(0.25)
    msg = f"Timed out waiting for screen to not contain {needle!r}"
    raise TimeoutError(msg)


async def main(connection: iterm2.Connection) -> None:
    _ensure_iterm2_running()

    app = await iterm2.async_get_app(connection)
    window = app.current_terminal_window
    if window is None:
        raise RuntimeError("No active iTerm2 window found")

    subprocess.run(["osascript", "-e", 'tell application "iTerm2" to activate'], check=False)

    root = _repo_root()
    out_dir = _artifacts_dir()

    # Launch yathaavat in a fresh tab and drive launch/connect flows.
    tab = await window.async_create_tab()
    session = tab.current_session
    await session.async_set_name("yathaavat")
    await session.async_activate()
    await tab.async_activate()

    await session.async_send_text(f"cd {root}\n")
    await session.async_send_text("echo __YATHAAVAT_MARKER__\n")
    await _wait_for_screen_contains(session, "__YATHAAVAT_MARKER__", timeout_s=8)

    marker_png = out_dir / "shell_marker.png"
    _screencapture(marker_png)

    await session.async_send_text("clear\n")
    await asyncio.sleep(0.4)
    await session.async_send_text("make run\n")

    try:
        await _wait_for_screen_contains(session, "Ctrl+P palette", timeout_s=25)
        screen_text = await _screen_text(session)
        (out_dir / "tui_main.txt").write_text(screen_text, encoding="utf-8")
        main_png = out_dir / "tui_main.png"
        _screencapture(main_png)

        # Launch demo target (Ctrl+R).
        await session.async_send_text("\x12")  # Ctrl+R
        await _wait_for_screen_contains(session, "Launch under debugpy", timeout_s=6)
        await asyncio.sleep(0.4)
        await session.async_send_text("examples/demo_target.py\r")
        await _wait_for_screen_not_contains(session, "Launch under debugpy", timeout_s=6)

        # Wait for the breakpoint to be hit.
        await _wait_for_screen_contains(session, "PAUSED", timeout_s=25)
        paused_text = await _screen_text(session)
        (out_dir / "tui_paused.txt").write_text(paused_text, encoding="utf-8")
        paused_png = out_dir / "tui_paused.png"
        _screencapture(paused_png)

        # Toggle a breakpoint at the current line (b).
        await session.async_send_text("b")
        await asyncio.sleep(0.8)
        bp_png = out_dir / "tui_breakpoint.png"
        _screencapture(bp_png)

        # Step over (n).
        await session.async_send_text("n")
        await _wait_for_screen_contains(session, "Stopped (step)", timeout_s=12)
        step_png = out_dir / "tui_step.png"
        _screencapture(step_png)

        # Continue (c) and wait for demo output.
        await session.async_send_text("c")
        await _wait_for_screen_contains(session, "RUNNING", timeout_s=8)
        await _wait_for_screen_contains(session, "TOTAL", timeout_s=12)
        running_png = out_dir / "tui_running.png"
        _screencapture(running_png)

        await session.async_send_text("\x10")  # Ctrl+P
        await asyncio.sleep(0.7)
        pal_text = await _screen_text(session)
        (out_dir / "tui_palette.txt").write_text(pal_text, encoding="utf-8")
        pal_png = out_dir / "tui_palette.png"
        _screencapture(pal_png)

        await session.async_send_text("\x1b")  # Esc
        await asyncio.sleep(0.3)

        await session.async_send_text("\x01")  # Ctrl+A
        await asyncio.sleep(0.8)
        await session.async_send_text("python")
        await asyncio.sleep(0.8)
        attach_png = out_dir / "tui_attach.png"
        _screencapture(attach_png)

        await session.async_send_text("\x1b")  # Esc
        await asyncio.sleep(0.3)

        await session.async_send_text("\x11")  # Ctrl+Q
        await asyncio.sleep(0.4)

        print(f"Wrote {main_png}")
        print(f"Wrote {pal_png}")
        print(f"Wrote {paused_png}")
        print(f"Wrote {bp_png}")
        print(f"Wrote {step_png}")
        print(f"Wrote {running_png}")
        print(f"Wrote {attach_png}")
    except Exception:
        error_text = await _screen_text(session)
        (out_dir / "tui_error.txt").write_text(error_text, encoding="utf-8")
        error_png = out_dir / "tui_error.png"
        _screencapture(error_png)
        try:
            await session.async_send_text("\x11")  # Ctrl+Q
        except Exception:
            pass
        raise


if __name__ == "__main__":
    iterm2.run_until_complete(main)
