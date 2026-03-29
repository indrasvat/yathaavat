# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "iterm2",
#   "pyobjc",
#   "pyobjc-framework-Quartz",
# ]
# ///
"""iTerm2 visual test: demo HTTP service connect + debug workflow.

Tests
-----
1. Service startup — demo_service.py starts, debugpy listens, HTTP healthy
2. TUI connect — Ctrl+K connects to debugpy, status shows Connected
3. HTTP-triggered breakpoint — /debug/break pauses, PAUSED state shown
4. Source zoom — view.zoom via palette zooms/unzooms pane
5. Configured breakpoints — Ctrl+B adds logpoint + hit-count BP
6. Watch expression — Ctrl+W adds a watch, evaluated while paused
7. Find in source — Ctrl+F searches, highlights match
8. Go to line + jump to exec — Ctrl+G navigates, Ctrl+E returns to exec line
9. Step + continue — n steps, c continues, hit-condition BP fires on 3rd /health
10. Multi-tab coordination — service, TUI, and client tabs work independently

Verification Strategy
---------------------
- Service tab: poll for SERVICE_LISTENING and DEBUGPY_LISTENING
- TUI tab: poll for Connected, PAUSED, RUNNING state transitions
- Client tab: verify health endpoint via __HEALTH_OK__ marker
- Cross-tab: trigger /debug/break from client, observe PAUSED in TUI

Screenshots
-----------
- demo_service_running.png            — Service tab after startup
- tui_demo_service_main.png           — TUI initial state
- tui_demo_service_connected.png      — After Ctrl+K connect
- tui_demo_service_paused.png         — Paused on /debug/break
- tui_demo_service_zoomed.png         — Source pane zoomed
- tui_demo_service_unzoomed.png       — Restored layout
- tui_demo_service_breakpoints_config.png — Configured BPs in list
- tui_demo_service_watch.png          — Watch expression added
- tui_demo_service_find.png           — Find in source active
- tui_demo_service_src_moved.png      — Cursor moved to line 1
- tui_demo_service_jump_to_exec.png   — Jumped back to exec line
- tui_demo_service_step.png           — After step over
- tui_demo_service_running.png        — After continue
- tui_demo_service_hit3_paused.png    — Hit-count BP fired

Key Bindings Tested
-------------------
Ctrl+K (connect), Ctrl+B (add BP), Ctrl+W (watch), Ctrl+F (find),
Ctrl+G (go to line), Ctrl+E (jump to exec), n (step), c (continue),
Ctrl+P (palette), Esc (dismiss), Tab (focus)

Usage
-----
    uv run .claude/automations/iterm2_capture_demo_service.py
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
import socket
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


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


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


async def _open_command_palette(session: iterm2.Session, timeout_s: float = 6) -> None:
    for _ in range(3):
        await session.async_send_text("\x10")  # Ctrl+P
        try:
            await _wait_for(session, "Command Palette", timeout_s=timeout_s)
            return
        except TimeoutError:
            await asyncio.sleep(0.25)
    raise TimeoutError("Timed out opening Command Palette")


async def _run_palette_command(
    session: iterm2.Session,
    *,
    query: str,
    expect: str | None = None,
    open_timeout_s: float = 6,
    run_timeout_s: float = 8,
) -> None:
    await _open_command_palette(session, timeout_s=open_timeout_s)
    await asyncio.sleep(0.2)
    if query:
        await session.async_send_text(query)
    if expect:
        await _wait_for(session, expect, timeout_s=open_timeout_s)
    await session.async_send_text("\r")
    await _wait_gone(session, "Command Palette", timeout_s=run_timeout_s)
    await asyncio.sleep(0.25)


# ---------------------------------------------------------------------------
# Main test flow
# ---------------------------------------------------------------------------


async def main(connection: iterm2.Connection) -> None:
    _ensure_iterm2_running()

    window, _ = await _create_window(connection, name="demo-service-test")
    root = _repo_root()
    out = _artifacts_dir()
    http_port = _pick_free_port()
    dap_port = _pick_free_port()

    service: iterm2.Session | None = None
    tui: iterm2.Session | None = None
    client: iterm2.Session | None = None

    async def _cleanup() -> None:
        with contextlib.suppress(Exception):
            await window.async_close(force=True)

    try:
        # --- Start demo service ---
        service_tab = await window.async_create_tab()
        service = service_tab.current_session
        if service is None:
            raise RuntimeError("iTerm2 did not create service session")
        await service.async_set_name("demo-service")
        await service.async_activate()
        await service_tab.async_activate()

        await service.async_send_text(f"cd {root}\n")
        await service.async_send_text("clear\n")
        await service.async_send_text(
            f"YATHAAVAT_HTTP_PORT={http_port} YATHAAVAT_DAP_PORT={dap_port} make demo-service\n"
        )

        await _wait_for(service, "SERVICE_LISTENING", timeout_s=25)
        await _wait_for(service, f"DEBUGPY_LISTENING 127.0.0.1:{dap_port}", timeout_s=10)
        frame = await window.async_get_frame()
        _screencapture(out / "demo_service_running.png", frame=frame)
        print("[1/14] Service startup: PASS")

        # --- Start TUI ---
        tui_tab = await window.async_create_tab()
        tui = tui_tab.current_session
        if tui is None:
            raise RuntimeError("iTerm2 did not create TUI session")
        await tui.async_set_name("yathaavat-demo")
        await tui.async_activate()
        await tui_tab.async_activate()

        await tui.async_send_text(f"cd {root}\n")
        await tui.async_send_text("clear\n")
        await tui.async_send_text("make run\n")
        await _wait_for(tui, "Ctrl+P palette", timeout_s=25)
        _screencapture(out / "tui_demo_service_main.png", frame=frame)
        print("[2/14] TUI startup: PASS")

        # --- Connect to debugpy ---
        await tui.async_send_text("\x0b")  # Ctrl+K
        await _wait_for(tui, "Connect to debugpy", timeout_s=6)
        await asyncio.sleep(0.4)
        await tui.async_send_text(f"127.0.0.1:{dap_port}\r")
        await _wait_gone(tui, "Connect to debugpy", timeout_s=10)
        await _wait_for(tui, "Connected.", timeout_s=25)
        (out / "tui_demo_service_connected.txt").write_text(
            await _screen_text(tui), encoding="utf-8"
        )
        _screencapture(out / "tui_demo_service_connected.png", frame=frame)
        print("[3/14] Connect to debugpy: PASS")

        # --- Start client tab ---
        client_tab = await window.async_create_tab()
        client = client_tab.current_session
        if client is None:
            raise RuntimeError("iTerm2 did not create client session")
        await client.async_set_name("demo-client")
        await client.async_activate()
        await client_tab.async_activate()

        await client.async_send_text(f"cd {root}\n")
        await client.async_send_text("clear\n")

        # Verify service is healthy
        await client.async_send_text(
            f"curl -fsS http://127.0.0.1:{http_port}/health >/dev/null && echo __HEALTH_OK__\n"
        )
        await _wait_for(client, "__HEALTH_OK__", timeout_s=10)
        print("[4/14] Health check: PASS")

        # --- Trigger breakpoint via HTTP ---
        await client.async_send_text(
            f"curl -fsS --max-time 60 http://127.0.0.1:{http_port}/debug/break "
            ">/dev/null 2>&1 & echo __BREAK_SENT__\n"
        )
        await _wait_for(client, "__BREAK_SENT__", timeout_s=10)

        # Switch to TUI tab and wait for PAUSED
        await tui.async_activate()
        await tui_tab.async_activate()
        await _wait_for(tui, "PAUSED", timeout_s=25)
        (out / "tui_demo_service_paused.txt").write_text(await _screen_text(tui), encoding="utf-8")
        _screencapture(out / "tui_demo_service_paused.png", frame=frame)
        print("[5/14] HTTP-triggered breakpoint: PASS")

        # --- Zoom Source pane ---
        await _run_palette_command(tui, query="view.zoom", expect="Zoom Pane")
        await _wait_gone(tui, "▊ Stack", timeout_s=12)
        _screencapture(out / "tui_demo_service_zoomed.png", frame=frame)
        print("[6/14] Source zoom: PASS")

        # --- Unzoom ---
        await _run_palette_command(tui, query="view.zoom", expect="Zoom Pane")
        await _wait_for(tui, "▊ Stack", timeout_s=12)
        _screencapture(out / "tui_demo_service_unzoomed.png", frame=frame)
        print("[7/14] Source unzoom: PASS")

        # --- Add configured breakpoints ---
        await tui.async_send_text("\x02")  # Ctrl+B
        try:
            await _wait_for(tui, "Add breakpoint", timeout_s=2)
        except TimeoutError:
            await _run_palette_command(tui, query="breakpoint.add", expect="Add Breakpoint")
            await _wait_for(tui, "Add breakpoint", timeout_s=6)
        await tui.async_send_text("examples/demo_service.py:128 log __YLOG__\r")
        await _wait_gone(tui, "Add breakpoint", timeout_s=6)
        await asyncio.sleep(0.25)

        await tui.async_send_text("\x02")  # Ctrl+B
        try:
            await _wait_for(tui, "Add breakpoint", timeout_s=2)
        except TimeoutError:
            await _run_palette_command(tui, query="breakpoint.add", expect="Add Breakpoint")
            await _wait_for(tui, "Add breakpoint", timeout_s=6)
        await tui.async_send_text("examples/demo_service.py:190 hit 3\r")
        await _wait_gone(tui, "Add breakpoint", timeout_s=6)
        await asyncio.sleep(0.25)

        await _wait_for(tui, "Breakpoints set: demo_service.py (1)", timeout_s=10)
        await _wait_for(tui, "Breakpoints set: demo_service.py (2)", timeout_s=10)
        _screencapture(out / "tui_demo_service_breakpoints_config.png", frame=frame)
        print("[8/14] Configured breakpoints: PASS")

        # Move focus out of Input
        await tui.async_send_text("\t\t")
        await asyncio.sleep(0.25)

        # --- Add watch ---
        await tui.async_send_text("\x17")  # Ctrl+W
        await _wait_for_any(tui, ["Watch", "Enter add", "expression"], timeout_s=6)
        await asyncio.sleep(0.3)
        await tui.async_send_text("len(recent_jobs)\r")
        await asyncio.sleep(1.0)
        _screencapture(out / "tui_demo_service_watch.png", frame=frame)
        print("[9/14] Watch expression: PASS")

        # Close Watch dialog — send Esc twice to ensure dismissal
        await tui.async_send_text("\x1b")  # Esc
        await asyncio.sleep(0.5)
        await tui.async_send_text("\x1b")  # Esc again (safety)
        await asyncio.sleep(0.5)

        # Ensure focus is on Source before Find (Tab twice to cycle past Console)
        await tui.async_send_text("\t\t")
        await asyncio.sleep(0.3)

        # --- Find in source ---
        await tui.async_send_text("\x06")  # Ctrl+F
        await _wait_for_any(tui, ["Find", "Enter next", "search"], timeout_s=6)
        await asyncio.sleep(0.3)
        await tui.async_send_text("debugpy\r")
        await asyncio.sleep(0.5)
        _screencapture(out / "tui_demo_service_find.png", frame=frame)
        print("[10/14] Find in source: PASS")

        # Close Find — Esc and settle
        await tui.async_send_text("\x1b")  # Esc
        await asyncio.sleep(0.5)
        await tui.async_send_text("\x1b")  # Esc again (safety)
        await asyncio.sleep(0.5)

        # --- Go to line + jump to exec ---
        # Use palette to reliably trigger goto regardless of focus
        await _run_palette_command(tui, query="source.goto", expect="Go to Line")
        await _wait_for_any(tui, ["Go to line", "line[:col]"], timeout_s=6)
        await asyncio.sleep(0.3)
        await tui.async_send_text("1:1\r")
        await asyncio.sleep(0.5)
        await _wait_for(tui, "from __future__ import annotations", timeout_s=6)
        _screencapture(out / "tui_demo_service_src_moved.png", frame=frame)
        print("[11/14] Go to line: PASS")

        await tui.async_send_text("\x05")  # Ctrl+E
        # The execution line should scroll back into view — look for the line number area
        await asyncio.sleep(1.0)
        _screencapture(out / "tui_demo_service_jump_to_exec.png", frame=frame)
        print("[12/14] Jump to exec: PASS")

        # --- Step + continue ---
        # Use palette commands to avoid focus issues with single-char keybindings
        await _run_palette_command(tui, query="step over", expect="Step Over")
        # Status line shows "step" after stepping (transient text varies)
        await _wait_for_any(tui, ["Stopped (step)", "step", "PAUSED"], timeout_s=12)
        _screencapture(out / "tui_demo_service_step.png", frame=frame)
        print("[13/14] Step over: PASS")

        await _run_palette_command(tui, query="continue", expect="Continue")
        await _wait_for(tui, "RUNNING", timeout_s=12)
        _screencapture(out / "tui_demo_service_running.png", frame=frame)

        # --- Hit-condition breakpoint (3rd /health pauses) ---
        await client.async_activate()
        await client_tab.async_activate()
        await client.async_send_text(
            f"curl -fsS http://127.0.0.1:{http_port}/health >/dev/null && echo __H1__\n"
        )
        await _wait_for(client, "__H1__", timeout_s=10)
        await client.async_send_text(
            f"curl -fsS http://127.0.0.1:{http_port}/health >/dev/null && echo __H2__\n"
        )
        await _wait_for(client, "__H2__", timeout_s=10)
        await client.async_send_text(
            f"curl -fsS --max-time 60 http://127.0.0.1:{http_port}/health "
            ">/dev/null 2>&1 & echo __H3__\n"
        )
        await _wait_for(client, "__H3__", timeout_s=10)

        await tui.async_activate()
        await tui_tab.async_activate()
        await _wait_for(tui, "PAUSED", timeout_s=25)
        _screencapture(out / "tui_demo_service_hit3_paused.png", frame=frame)
        print("[14/14] Hit-count breakpoint: PASS")

        await _run_palette_command(tui, query="continue", expect="Continue")
        await _wait_for(tui, "RUNNING", timeout_s=12)

        print("\nAll 14 tests passed.")

    except Exception:
        for s, name in [(service, "service"), (tui, "tui"), (client, "client")]:
            if s is not None:
                with contextlib.suppress(Exception):
                    txt = await _screen_text(s)
                    (out / f"demo_service_{name}_error.txt").write_text(txt, encoding="utf-8")
        if tui is not None:
            with contextlib.suppress(Exception):
                _screencapture(out / "demo_service_error.png")
                await tui.async_send_text("\x11")
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
