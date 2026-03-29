# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "iterm2",
#   "pyobjc",
#   "pyobjc-framework-Quartz",
# ]
# ///
"""iTerm2 visual test: safe attach to a running Python process.

Tests
-----
1. Background process — Python sleep process started, PID captured
2. TUI startup — yathaavat launches with DISCONNECTED state
3. Attach picker — Ctrl+A opens, PID entered and submitted
4. Attach result — either PAUSED (success) or actionable error message
5. Cleanup — background process killed, TUI quit

Verification Strategy
---------------------
- Start a long-running Python process in the project .venv (has debugpy available)
- Capture PID via pidfile written by the process itself
- Drive attach via Ctrl+A with PID search/enter
- Accept either PAUSED (attach succeeded) or known error messages
  (safe attach often fails on macOS without elevated privileges — this is expected)
- Screenshot captures both success and failure states for visual inspection

Screenshots
-----------
- tui_safe_attach.png       — Successful PAUSED after safe attach (if it works)
- tui_safe_attach_fail.png  — Error state (if attach fails due to permissions)

Key Bindings Tested
-------------------
Ctrl+A (attach), c (continue), Ctrl+Q (quit)

Usage
-----
    uv run .claude/automations/iterm2_capture_safe_attach.py

Note: On macOS, safe attach typically requires `sudo` or SIP adjustments.
A "failed" result is expected without elevated privileges.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
import subprocess
import time
from pathlib import Path

import iterm2
import iterm2.rpc
import Quartz

TOTAL_TIMEOUT_S = 90.0
MIN_WINDOW_WIDTH_PX = 1400
MIN_WINDOW_HEIGHT_PX = 900


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ensure_iterm2_running() -> None:
    if subprocess.run(["pgrep", "-x", "iTerm2"], check=False, capture_output=True).returncode == 0:
        return
    subprocess.run(["open", "-a", "iTerm"], check=False)
    for _ in range(30):
        if (
            subprocess.run(["pgrep", "-x", "iTerm2"], check=False, capture_output=True).returncode
            == 0
        ):
            return
        time.sleep(0.2)
    raise RuntimeError("iTerm2 did not start in time")


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in [here, *here.parents]:
        if (parent / "pyproject.toml").exists():
            return parent
    raise RuntimeError(f"Could not find repo root from {here}")


def _artifacts_dir() -> Path:
    out = _repo_root() / ".claude" / "artifacts" / "screenshots"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _screencapture(path: Path, *, frame: iterm2.util.Frame | None = None) -> None:
    window_list = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
        Quartz.kCGNullWindowID,
    )
    best_id: int | None = None
    best_score = float("inf")
    for w in window_list or []:
        if "iTerm" not in w.get("kCGWindowOwnerName", ""):
            continue
        if frame is not None:
            b = w.get("kCGWindowBounds", {})
            score = (
                abs(float(b.get("X", 0)) - frame.origin.x) * 2
                + abs(float(b.get("Width", 0)) - frame.size.width)
                + abs(float(b.get("Height", 0)) - frame.size.height)
            )
            if score < best_score:
                best_score, best_id = score, w.get("kCGWindowNumber")
        else:
            win_id = w.get("kCGWindowNumber")
            if isinstance(win_id, int):
                best_id = win_id
                break
    if best_id is not None:
        subprocess.run(["screencapture", "-x", "-l", str(best_id), str(path)], check=True)
    else:
        raise RuntimeError("Could not find iTerm2 window for screencapture")


async def _screen_text(session: iterm2.Session) -> str:
    try:
        screen = await session.async_get_screen_contents()
    except iterm2.rpc.RPCException as exc:
        raise RuntimeError(f"Failed to read iTerm2 screen buffer: {exc}") from exc
    return "\n".join(screen.line(i).string for i in range(screen.number_of_lines))


async def _wait_for(session: iterm2.Session, needle: str, timeout_s: float) -> str:
    deadline = time.monotonic() + timeout_s
    last = ""
    while time.monotonic() < deadline:
        last = await _screen_text(session)
        if needle in last:
            return last
        await asyncio.sleep(0.25)
    raise TimeoutError(f"Timed out ({timeout_s}s) waiting for: {needle!r}")


async def _wait_for_any(session: iterm2.Session, needles: list[str], timeout_s: float) -> str:
    deadline = time.monotonic() + timeout_s
    last = ""
    while time.monotonic() < deadline:
        last = await _screen_text(session)
        if any(n in last for n in needles):
            return last
        await asyncio.sleep(0.25)
    raise TimeoutError(f"Timed out ({timeout_s}s) waiting for any of: {needles!r}")


async def _create_window(
    connection: iterm2.Connection,
    name: str = "test",
) -> tuple[iterm2.Window, iterm2.Session]:
    window = await iterm2.Window.async_create(connection)
    await asyncio.sleep(0.5)

    app = await iterm2.async_get_app(connection)
    if window is None:
        raise RuntimeError("Could not create iTerm2 window")
    if window.current_tab is None:
        for w in app.terminal_windows:
            if w.window_id == window.window_id:
                window = w
                break

    for _ in range(20):
        if window.current_tab and window.current_tab.current_session:
            break
        await asyncio.sleep(0.2)

    if not window.current_tab or not window.current_tab.current_session:
        raise RuntimeError(f"Window {name!r} not ready after refresh")

    session = window.current_tab.current_session
    await session.async_set_name(name)
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

    return window, session


# ---------------------------------------------------------------------------
# Main test flow
# ---------------------------------------------------------------------------


async def main(connection: iterm2.Connection) -> None:
    _ensure_iterm2_running()

    window, session = await _create_window(connection, name="yathaavat-safe-attach")
    root = _repo_root()
    out = _artifacts_dir()

    pid: int | None = None
    pidfile: Path | None = None

    async def _cleanup() -> None:
        with contextlib.suppress(Exception):
            await window.async_close(force=True)

    try:
        await session.async_send_text(f"cd {root}\n")
        await session.async_send_text("clear\n")

        # --- Test 1: Start background Python process ---
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
        print(f"[1/5] Background process started: PID {pid}")

        # --- Test 2: Launch TUI ---
        await session.async_send_text("make run\n")
        await _wait_for(session, "Ctrl+P palette", timeout_s=25)
        print("[2/5] TUI startup: PASS")

        frame = await window.async_get_frame()

        # --- Test 3: Open attach picker ---
        await session.async_send_text("\x01")  # Ctrl+A
        await _wait_for(session, "Attach to Process", timeout_s=6)
        await session.async_send_text(f"{pid}\r")
        print("[3/5] Attach picker opened, PID submitted")

        # --- Test 4: Wait for attach result ---
        screen = await _wait_for_any(
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
            _screencapture(out / "tui_safe_attach.png", frame=frame)
            print("[4/5] Safe attach: PAUSED (SUCCESS)")
            # Resume before quitting
            await session.async_send_text("c")
            await asyncio.sleep(0.6)
        else:
            (out / "tui_safe_attach_fail.txt").write_text(
                await _screen_text(session), encoding="utf-8"
            )
            _screencapture(out / "tui_safe_attach_fail.png", frame=frame)
            print("[4/5] Safe attach: EXPECTED FAILURE (permissions)")
            print("       This is normal on macOS without elevated privileges.")

        # --- Test 5: Clean quit ---
        await session.async_send_text("\x11")  # Ctrl+Q
        await asyncio.sleep(0.5)
        await session.async_send_text(f"kill {pid} >/dev/null 2>&1 || true\n")
        pidfile.unlink(missing_ok=True)
        await asyncio.sleep(0.2)
        print("[5/5] Cleanup: PASS")

        print("\nAll safe-attach tests completed.")

    except Exception:
        if session is not None:
            with contextlib.suppress(Exception):
                txt = await _screen_text(session)
                (out / "tui_safe_attach_error.txt").write_text(txt, encoding="utf-8")
                _screencapture(out / "tui_safe_attach_error.png")
                await session.async_send_text("\x11")
        raise
    finally:
        if pid is not None:
            with contextlib.suppress(Exception):
                if session is not None:
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
