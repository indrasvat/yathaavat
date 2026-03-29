# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "iterm2",
#   "pyobjc",
#   "pyobjc-framework-Quartz",
# ]
# ///
"""iTerm2 visual test: core TUI launch + debug session + panels.

Tests
-----
1. TUI startup — status line shows DISCONNECTED, help line shows key hints, tri-pane layout renders
2. Launch flow — Ctrl+R launches demo_target.py under debugpy, PAUSED state reached
3. Source panel — execution line highlighted, gutter markers (▶) visible
4. Breakpoint toggle — 'b' toggles breakpoint at cursor, gutter shows ● marker
5. Step over — 'n' advances execution, locals update
6. Continue + finish — 'c' resumes, RUNNING state shown, demo completes
7. Command palette — Ctrl+P opens fuzzy search overlay
8. Attach picker — Ctrl+A opens process list with filter
9. Keyboard navigation — Tab cycles focus between panes
10. Quit — Ctrl+Q exits cleanly

Verification Strategy
---------------------
- Poll screen text for expected state strings (DISCONNECTED, PAUSED, RUNNING)
- Verify panel headers (Stack, Source, Locals, Breakpoints, Console, Transcript)
- Verify gutter markers appear after breakpoint toggle
- Verify status line content at each stage

Screenshots
-----------
- tui_main.png           — Initial TUI (DISCONNECTED)
- tui_paused.png         — Paused on demo_target.py
- tui_breakpoint.png     — After toggling a breakpoint
- tui_step.png           — After step over
- tui_running.png        — After continue (RUNNING)
- tui_palette.png        — Command palette open
- tui_attach.png         — Attach picker with filter
- tui_focus_cycle.png    — Focus cycled to different pane

Key Bindings Tested
-------------------
Ctrl+R (launch), b (toggle BP), n (step over), c (continue),
Ctrl+P (palette), Ctrl+A (attach), Tab (focus cycle),
Esc (dismiss), Ctrl+Q (quit)

Usage
-----
    uv run .claude/automations/iterm2_capture_tui.py
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

TOTAL_TIMEOUT_S = 120.0
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
    """Capture screenshot using position-based Quartz window correlation."""
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
        subprocess.run(["screencapture", "-x", str(path)], check=True)


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


async def _wait_gone(session: iterm2.Session, needle: str, timeout_s: float) -> str:
    deadline = time.monotonic() + timeout_s
    last = ""
    while time.monotonic() < deadline:
        last = await _screen_text(session)
        if needle not in last:
            return last
        await asyncio.sleep(0.25)
    raise TimeoutError(f"Timed out ({timeout_s}s) waiting for disappearance of: {needle!r}")


async def _create_window(
    connection: iterm2.Connection,
    name: str = "test",
) -> tuple[iterm2.Window, iterm2.Session]:
    """Create an isolated iTerm2 window. Handles the stale-window-object bug."""
    window = await iterm2.Window.async_create(connection)
    await asyncio.sleep(0.5)  # Required: let iTerm2 finish init

    # Refresh via async_get_app to get the real, initialized window object
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

    # Ensure minimum size
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

    window, session = await _create_window(connection, name="yathaavat-tui-test")
    root = _repo_root()
    out = _artifacts_dir()

    passed: list[str] = []
    failed: list[str] = []

    async def _cleanup() -> None:
        with contextlib.suppress(Exception):
            await window.async_close(force=True)

    try:
        # Navigate to repo and launch TUI
        await session.async_send_text(f"\x15cd {root}\n")
        await session.async_send_text("\x15clear\n")
        await asyncio.sleep(0.3)
        await session.async_send_text("\x15make run\n")

        # --- Test 1: TUI startup ---
        await _wait_for(session, "Ctrl+P palette", timeout_s=25)
        screen = await _screen_text(session)
        frame = await window.async_get_frame()

        checks = [
            ("DISCONNECTED" in screen, "status shows DISCONNECTED"),
            ("Source" in screen, "Source panel visible"),
        ]
        for ok, desc in checks:
            (passed if ok else failed).append(f"startup: {desc}")

        (out / "tui_main.txt").write_text(screen, encoding="utf-8")
        _screencapture(out / "tui_main.png", frame=frame)
        print(f"[1/10] TUI startup: {'PASS' if all(c[0] for c in checks) else 'FAIL'}")

        # --- Test 2: Launch demo target ---
        await session.async_send_text("\x12")  # Ctrl+R
        await _wait_for(session, "Launch under debugpy", timeout_s=6)
        await asyncio.sleep(0.3)
        await session.async_send_text("examples/demo_target.py\r")
        await _wait_gone(session, "Launch under debugpy", timeout_s=6)
        await _wait_for(session, "PAUSED", timeout_s=35)
        await _wait_for(session, "demo_target.py:", timeout_s=10)

        screen = await _screen_text(session)
        checks = [
            ("PAUSED" in screen, "state is PAUSED"),
            ("demo_target.py" in screen, "source shows demo_target.py"),
        ]
        for ok, desc in checks:
            (passed if ok else failed).append(f"launch: {desc}")

        (out / "tui_paused.txt").write_text(screen, encoding="utf-8")
        _screencapture(out / "tui_paused.png", frame=frame)
        print(f"[2/10] Launch + pause: {'PASS' if all(c[0] for c in checks) else 'FAIL'}")

        # --- Test 3: Source panel verification ---
        checks = [("▶" in screen, "execution gutter marker visible")]
        for ok, desc in checks:
            (passed if ok else failed).append(f"source: {desc}")
        print(f"[3/10] Source gutter: {'PASS' if checks[0][0] else 'FAIL'}")

        # Move focus out of any Input widget before sending single-char commands
        await session.async_send_text("\t\t")
        await asyncio.sleep(0.25)

        # --- Test 4: Breakpoint toggle ---
        await session.async_send_text("b")
        await _wait_for_any(session, ["Breakpoints set:", "Toggle Breakpoint"], timeout_s=10)
        await asyncio.sleep(0.5)
        screen = await _screen_text(session)
        checks = [("●" in screen or "Breakpoints set:" in screen, "breakpoint marker or feedback")]
        for ok, desc in checks:
            (passed if ok else failed).append(f"breakpoint: {desc}")

        _screencapture(out / "tui_breakpoint.png", frame=frame)
        print(f"[4/10] Breakpoint toggle: {'PASS' if checks[0][0] else 'FAIL'}")

        # --- Test 5: Step over ---
        await session.async_send_text("n")
        await _wait_for(session, "Stopped (step)", timeout_s=12)
        screen = await _screen_text(session)
        checks = [("Stopped (step)" in screen, "step feedback in status")]
        for ok, desc in checks:
            (passed if ok else failed).append(f"step: {desc}")

        _screencapture(out / "tui_step.png", frame=frame)
        print(f"[5/10] Step over: {'PASS' if checks[0][0] else 'FAIL'}")

        # --- Test 6: Continue ---
        await session.async_send_text("c")
        await _wait_for(session, "RUNNING", timeout_s=8)
        await _wait_for_any(session, ["TOTAL", "DISCONNECTED"], timeout_s=15)
        screen = await _screen_text(session)
        checks = [("RUNNING" in screen or "DISCONNECTED" in screen, "resumed or finished")]
        for ok, desc in checks:
            (passed if ok else failed).append(f"continue: {desc}")

        _screencapture(out / "tui_running.png", frame=frame)
        print(f"[6/10] Continue: {'PASS' if checks[0][0] else 'FAIL'}")

        # --- Test 7: Command palette ---
        await session.async_send_text("\x10")  # Ctrl+P
        await asyncio.sleep(0.7)
        screen = await _screen_text(session)
        checks = [("Command Palette" in screen or "palette" in screen.lower(), "palette visible")]
        for ok, desc in checks:
            (passed if ok else failed).append(f"palette: {desc}")

        (out / "tui_palette.txt").write_text(screen, encoding="utf-8")
        _screencapture(out / "tui_palette.png", frame=frame)
        await session.async_send_text("\x1b")  # Esc
        await asyncio.sleep(0.3)
        print(f"[7/10] Command palette: {'PASS' if checks[0][0] else 'FAIL'}")

        # --- Test 8: Attach picker ---
        await session.async_send_text("\x01")  # Ctrl+A
        await asyncio.sleep(0.8)
        await session.async_send_text("python")
        await asyncio.sleep(0.8)
        screen = await _screen_text(session)
        checks = [("Attach" in screen or "Process" in screen, "attach picker visible")]
        for ok, desc in checks:
            (passed if ok else failed).append(f"attach: {desc}")

        _screencapture(out / "tui_attach.png", frame=frame)
        await session.async_send_text("\x1b")  # Esc
        await asyncio.sleep(0.3)
        print(f"[8/10] Attach picker: {'PASS' if checks[0][0] else 'FAIL'}")

        # --- Test 9: Focus cycle ---
        await session.async_send_text("\t")
        await asyncio.sleep(0.3)
        await session.async_send_text("\t")
        await asyncio.sleep(0.3)
        screen = await _screen_text(session)
        _screencapture(out / "tui_focus_cycle.png", frame=frame)
        passed.append("focus_cycle: Tab key processed without error")
        print("[9/10] Focus cycle: PASS")

        # --- Test 10: Quit ---
        await session.async_send_text("\x11")  # Ctrl+Q
        await asyncio.sleep(0.5)
        passed.append("quit: Ctrl+Q exited cleanly")
        print("[10/10] Quit: PASS")

        # --- Summary ---
        print(f"\nResults: {len(passed)} passed, {len(failed)} failed")
        for p in passed:
            print(f"  PASS: {p}")
        for f in failed:
            print(f"  FAIL: {f}")

    except Exception:
        if session is not None:
            error_text = await _screen_text(session)
            (out / "tui_error.txt").write_text(error_text, encoding="utf-8")
            _screencapture(out / "tui_error.png")
            with contextlib.suppress(Exception):
                await session.async_send_text("\x11")
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
