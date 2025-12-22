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
        if window is not None:
            with contextlib.suppress(Exception):
                await window.async_close(force=True)

    pid: int | None = None
    pidfile: Path | None = None
    session: iterm2.Session | None = None
    try:
        tab = await window.async_create_tab()
        session = tab.current_session
        if session is None:
            raise RuntimeError("iTerm2 did not create a yathaavat session")
        await session.async_set_name("yathaavat-safe-attach")
        await session.async_activate()
        await tab.async_activate()

        await session.async_send_text(f"cd {root}\n")
        await session.async_send_text("clear\n")

        # Start a long-running Python process in the project env so it has debugpy available.
        pidfile = Path("/tmp") / f"yathaavat_safe_pid_{time.time_ns()}.txt"
        code = (
            "import os, pathlib, time; "
            f"pathlib.Path({str(pidfile)!r}).write_text(str(os.getpid())); "
            "time.sleep(120)"
        )
        await session.async_send_text(f'.venv/bin/python -c "{code}" &\n')
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not pidfile.exists():
            await asyncio.sleep(0.1)
        if not pidfile.exists():
            raise RuntimeError(f"Timed out waiting for pidfile {pidfile}")
        pid = int(pidfile.read_text(encoding="utf-8").strip())

        await session.async_send_text("make run\n")
        await _wait_for_screen_contains(session, "Ctrl+P palette", timeout_s=25)

        safe_png = out_dir / "tui_safe_attach.png"
        fail_png = out_dir / "tui_safe_attach_fail.png"
        fail_txt = out_dir / "tui_safe_attach_fail.txt"

        # Open attach picker and safe attach to PID via Enter in the search box.
        await session.async_send_text("\x01")  # Ctrl+A
        await _wait_for_screen_contains(session, "Attach to Process", timeout_s=6)
        await session.async_send_text(f"{pid}\r")

        # Wait for either a successful stop, or a known attach failure message.
        screen = await _wait_for_screen_contains_any(
            session,
            [
                "PAUSED",
                "PID attach timed out",
                "PID attach failed:",
                "sys.remote_exec failed:",
            ],
            timeout_s=35,
        )

        if "PAUSED" in screen:
            _screencapture(safe_png)
            print(f"Wrote {safe_png}")
        else:
            fail_text = await _screen_text(session)
            fail_txt.write_text(fail_text, encoding="utf-8")
            _screencapture(fail_png)
            print(f"Wrote {fail_png}")
            print(f"Wrote {fail_txt}")
            print(
                "Safe attach did not reach PAUSED; this is often expected on macOS without privileges."
            )

        # Resume and quit.
        await session.async_send_text("c")
        await asyncio.sleep(0.6)
        await session.async_send_text("\x11")  # Ctrl+Q
        await asyncio.sleep(0.5)

        # Clean up the background process (best-effort).
        await session.async_send_text(f"kill {pid} >/dev/null 2>&1 || true\n")
        pidfile.unlink(missing_ok=True)
        await asyncio.sleep(0.2)

        # Note: the safe attach flow may not have succeeded; screenshots/logs were already printed.
    finally:
        if session is not None and pid is not None:
            with contextlib.suppress(Exception):
                await session.async_send_text(f"kill {pid} >/dev/null 2>&1 || true\n")
        if pidfile is not None:
            pidfile.unlink(missing_ok=True)
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
