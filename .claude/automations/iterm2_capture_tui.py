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
        if w.get("kCGWindowOwnerName") == "iTerm2":
            win_id = w.get("kCGWindowNumber")
            if isinstance(win_id, int):
                return win_id
    return None


def _screencapture(path: Path) -> None:
    win_id = _frontmost_iterm2_cgwindow_id()
    if win_id is None:
        # Fall back to full-screen capture if we can't locate the iTerm2 window id (e.g. CG window
        # metadata changes across macOS versions).
        subprocess.run(["screencapture", "-x", str(path)], check=True)
        return
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


async def _wait_for_screen_contains_any(
    session: iterm2.Session, needles: list[str], timeout_s: float
) -> str:
    deadline = time.monotonic() + timeout_s
    last = ""
    while time.monotonic() < deadline:
        last = await _screen_text(session)
        if any(n in last for n in needles):
            return last
        await asyncio.sleep(0.25)
    msg = f"Timed out waiting for screen to contain any of: {needles!r}"
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


async def _run_palette(session: iterm2.Session, query: str, *, timeout_s: float = 8) -> None:
    await session.async_send_text("\x10")  # Ctrl+P
    await _wait_for_screen_contains(session, "Command Palette", timeout_s=timeout_s)
    await asyncio.sleep(0.25)
    await session.async_send_text(query)
    await asyncio.sleep(0.35)
    await session.async_send_text("\r")  # Enter
    await _wait_for_screen_not_contains(session, "Command Palette", timeout_s=timeout_s)


def _fn_key_sequence(n: int) -> str:
    # iTerm2 defaults to xterm-style sequences.
    match n:
        case 5:
            return "\x1b[15~"
        case 6:
            return "\x1b[17~"
        case 7:
            return "\x1b[18~"
        case 8:
            return "\x1b[19~"
        case 9:
            return "\x1b[20~"
        case 10:
            return "\x1b[21~"
        case 11:
            return "\x1b[23~"
        case 12:
            return "\x1b[24~"
        case _:
            raise ValueError(f"Unsupported Fn key: F{n}")


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

        # Queue a breakpoint while disconnected (Ctrl+B).
        await session.async_send_text("\x02")  # Ctrl+B
        await _wait_for_screen_contains(session, "Add breakpoint", timeout_s=6)
        await asyncio.sleep(0.25)
        await session.async_send_text("examples/demo_target.py:29\r")
        await _wait_for_screen_not_contains(session, "Add breakpoint", timeout_s=6)
        await _wait_for_screen_contains(session, "Breakpoint queued:", timeout_s=8)

        # Launch demo target (Ctrl+R).
        await session.async_send_text("\x12")  # Ctrl+R
        await _wait_for_screen_contains(session, "Launch under debugpy", timeout_s=6)
        await asyncio.sleep(0.4)
        await session.async_send_text("examples/demo_target.py\r")
        await _wait_for_screen_not_contains(session, "Launch under debugpy", timeout_s=6)

        # First pause: our queued breakpoint.
        await _wait_for_screen_contains(session, "demo_target.py:29", timeout_s=25)
        queued_text = await _screen_text(session)
        (out_dir / "tui_paused_queued.txt").write_text(queued_text, encoding="utf-8")
        queued_png = out_dir / "tui_paused_queued.png"
        _screencapture(queued_png)

        # Continue to the debugpy.breakpoint() pause.
        await session.async_send_text("\t\t")
        await asyncio.sleep(0.1)
        await session.async_send_text(_fn_key_sequence(5))  # F5 continue
        await _wait_for_screen_contains_any(
            session,
            ["demo_target.py:30", "demo_target.py:31"],
            timeout_s=25,
        )
        paused_text = await _screen_text(session)
        (out_dir / "tui_paused.txt").write_text(paused_text, encoding="utf-8")
        paused_png = out_dir / "tui_paused.png"
        _screencapture(paused_png)

        # Ensure focus isn't inside an Input widget (printable keys get consumed).
        await session.async_send_text("\t\t")
        await asyncio.sleep(0.25)

        # Toggle a breakpoint at the current line.
        await session.async_send_text(_fn_key_sequence(9))  # F9 toggle breakpoint
        await _wait_for_screen_contains(session, "Breakpoints set:", timeout_s=10)
        await asyncio.sleep(0.5)
        bp_png = out_dir / "tui_breakpoint.png"
        _screencapture(bp_png)

        # Step over.
        await session.async_send_text(_fn_key_sequence(10))  # F10 step over
        await _wait_for_screen_contains(session, "Stopped (step)", timeout_s=12)
        step_png = out_dir / "tui_step.png"
        _screencapture(step_png)

        # Continue and wait for demo output.
        await session.async_send_text(_fn_key_sequence(5))  # F5 continue
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
        print(f"Wrote {queued_png}")
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
