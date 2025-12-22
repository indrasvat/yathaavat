# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "iterm2",
#   "pyobjc",
# ]
# ///

from __future__ import annotations

import asyncio
import contextlib
import signal
import subprocess
import time
from pathlib import Path

import iterm2
import iterm2.rpc
from Quartz import (
    CGWindowListCopyWindowInfo,
    kCGNullWindowID,
    kCGWindowListOptionOnScreenOnly,
)

TOTAL_TIMEOUT_S = 90.0
MIN_WINDOW_WIDTH_PX = 1400
MIN_WINDOW_HEIGHT_PX = 900


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
    try:
        screen = await session.async_get_screen_contents()
    except iterm2.rpc.RPCException as exc:
        raise RuntimeError(f"Failed to read iTerm2 screen buffer: {exc}") from exc
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


async def main(connection: iterm2.Connection) -> None:
    _ensure_iterm2_running()

    app = await iterm2.async_get_app(connection)
    await app.async_activate(raise_all_windows=False)
    window = await iterm2.Window.async_create(connection)
    if window is None:
        raise RuntimeError("Could not create iTerm2 automation window")
    await window.async_activate()
    try:
        frame = await window.async_get_frame()
        width = max(frame.size.width, MIN_WINDOW_WIDTH_PX)
        height = max(frame.size.height, MIN_WINDOW_HEIGHT_PX)
        if width != frame.size.width or height != frame.size.height:
            await window.async_set_frame(
                iterm2.util.Frame(
                    origin=frame.origin,
                    size=iterm2.util.Size(width=width, height=height),
                )
            )
    except Exception:
        pass

    root = _repo_root()
    out_dir = _artifacts_dir()

    async def _cleanup() -> None:
        with contextlib.suppress(Exception):
            await window.async_close(force=True)

    session: iterm2.Session | None = None
    try:
        # Launch yathaavat in a fresh tab and drive launch/connect flows.
        tab = await window.async_create_tab()
        session = tab.current_session
        if session is None:
            raise RuntimeError("iTerm2 did not create a yathaavat session")
        await session.async_set_name("yathaavat")
        await session.async_activate()
        await tab.async_activate()

        # Clear any partially-typed input so automation isn't affected by stray keystrokes.
        await session.async_send_text(f"\x15cd {root}\n")
        await session.async_send_text("\x15echo __YATHAAVAT_MARKER__\n")
        await _wait_for_screen_contains(session, "__YATHAAVAT_MARKER__", timeout_s=8)

        marker_png = out_dir / "shell_marker.png"
        _screencapture(marker_png)

        await session.async_send_text("\x15clear\n")
        await asyncio.sleep(0.4)
        await session.async_send_text("\x15make run\n")

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

        # Wait for the first PAUSED stop (we expect demo_target.py to stop, but don't assume a line).
        await _wait_for_screen_contains(session, "PAUSED", timeout_s=35)
        await _wait_for_screen_contains(session, "demo_target.py:", timeout_s=10)
        paused_text = await _screen_text(session)
        (out_dir / "tui_paused.txt").write_text(paused_text, encoding="utf-8")
        paused_png = out_dir / "tui_paused.png"
        _screencapture(paused_png)

        # Ensure focus isn't inside an Input widget (printable keys get consumed).
        await session.async_send_text("\t\t")
        await asyncio.sleep(0.25)

        # Toggle a breakpoint at the current line.
        await session.async_send_text("b")  # toggle breakpoint
        await _wait_for_screen_contains(session, "Breakpoints set:", timeout_s=10)
        await asyncio.sleep(0.5)
        bp_png = out_dir / "tui_breakpoint.png"
        _screencapture(bp_png)

        # Step over.
        await session.async_send_text("n")  # step over
        await _wait_for_screen_contains(session, "Stopped (step)", timeout_s=12)
        step_png = out_dir / "tui_step.png"
        _screencapture(step_png)

        # Continue and wait for demo output.
        await session.async_send_text("c")  # continue
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
        if session is not None:
            error_text = await _screen_text(session)
            (out_dir / "tui_error.txt").write_text(error_text, encoding="utf-8")
            error_png = out_dir / "tui_error.png"
            _screencapture(error_png)
            with contextlib.suppress(Exception):
                await session.async_send_text("\x11")  # Ctrl+Q
        raise
    finally:
        await asyncio.shield(_cleanup())


if __name__ == "__main__":
    async def _run(connection: iterm2.Connection) -> None:
        loop = asyncio.get_running_loop()

        def _cancel_all() -> None:
            for task in asyncio.all_tasks(loop):
                task.cancel()

        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(sig, _cancel_all)

        await asyncio.wait_for(main(connection), timeout=TOTAL_TIMEOUT_S)

    iterm2.run_until_complete(_run)
