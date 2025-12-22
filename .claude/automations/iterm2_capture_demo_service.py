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
import socket
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

TOTAL_TIMEOUT_S = 110.0
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


async def _open_command_palette(session: iterm2.Session, timeout_s: float) -> None:
    for _ in range(3):
        await session.async_send_text("\x10")  # Ctrl+P
        try:
            await _wait_for_screen_contains(session, "Command Palette", timeout_s=timeout_s)
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
    """Open the palette, type a query, then run the first result.

    This helper intentionally waits for `expect` (if provided) before pressing Enter
    to avoid racing the palette's incremental filtering.
    """

    await _open_command_palette(session, timeout_s=open_timeout_s)
    await asyncio.sleep(0.2)
    if query:
        await session.async_send_text(query)
    if expect:
        await _wait_for_screen_contains(session, expect, timeout_s=open_timeout_s)
    await session.async_send_text("\r")
    await _wait_for_screen_not_contains(session, "Command Palette", timeout_s=run_timeout_s)
    await asyncio.sleep(0.25)


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

    http_port = _pick_free_port()
    dap_port = _pick_free_port()

    service: iterm2.Session | None = None
    tui: iterm2.Session | None = None

    async def _cleanup() -> None:
        # Best-effort: close the automation window so we never leak tabs/sessions.
        if window is not None:
            with contextlib.suppress(Exception):
                await window.async_close(force=True)

    try:
        # --- Start demo service in a fresh tab ---
        service_tab = await window.async_create_tab()
        service = service_tab.current_session
        if service is None:
            raise RuntimeError("iTerm2 did not create a service session")
        await service.async_set_name("demo-service")
        await service.async_activate()
        await service_tab.async_activate()

        await service.async_send_text(f"cd {root}\n")
        await service.async_send_text("clear\n")
        await service.async_send_text(
            f"YATHAAVAT_HTTP_PORT={http_port} YATHAAVAT_DAP_PORT={dap_port} make demo-service\n"
        )

        await _wait_for_screen_contains(service, "SERVICE_LISTENING", timeout_s=25)
        await _wait_for_screen_contains(
            service, f"DEBUGPY_LISTENING 127.0.0.1:{dap_port}", timeout_s=10
        )
        (out_dir / "demo_service_running.txt").write_text(
            await _screen_text(service), encoding="utf-8"
        )
        demo_png = out_dir / "demo_service_running.png"
        _screencapture(demo_png)

        # --- Start yathaavat in a separate tab ---
        tui_tab = await window.async_create_tab()
        tui = tui_tab.current_session
        if tui is None:
            raise RuntimeError("iTerm2 did not create a TUI session")
        await tui.async_set_name("yathaavat-demo-service")
        await tui.async_activate()
        await tui_tab.async_activate()

        await tui.async_send_text(f"cd {root}\n")
        await tui.async_send_text("clear\n")
        await tui.async_send_text("make run\n")
        await _wait_for_screen_contains(tui, "Ctrl+P palette", timeout_s=25)
        tui_main_png = out_dir / "tui_demo_service_main.png"
        _screencapture(tui_main_png)

        # Connect to the debugpy server.
        await tui.async_send_text("\x0b")  # Ctrl+K
        await _wait_for_screen_contains(tui, "Connect to debugpy", timeout_s=6)
        await asyncio.sleep(0.4)
        await tui.async_send_text(f"127.0.0.1:{dap_port}\r")
        await _wait_for_screen_not_contains(tui, "Connect to debugpy", timeout_s=10)
        await _wait_for_screen_contains(tui, "Connected.", timeout_s=25)
        (out_dir / "tui_demo_service_connected.txt").write_text(
            await _screen_text(tui), encoding="utf-8"
        )
        tui_connected_png = out_dir / "tui_demo_service_connected.png"
        _screencapture(tui_connected_png)

        # Use a separate shell session to drive HTTP requests (the service session is busy).
        client_tab = await window.async_create_tab()
        client = client_tab.current_session
        if client is None:
            raise RuntimeError("iTerm2 did not create a client session")
        await client.async_set_name("demo-client")
        await client.async_activate()
        await client_tab.async_activate()

        await client.async_send_text(f"cd {root}\n")
        await client.async_send_text("clear\n")
        await client.async_send_text(
            f"curl -fsS http://127.0.0.1:{http_port}/health >/dev/null && echo __HEALTH_OK__\n"
        )
        await _wait_for_screen_contains(client, "__HEALTH_OK__", timeout_s=10)

        # Trigger a breakpoint via HTTP (request will pause until we continue, so background it).
        await client.async_send_text(
            f"curl -fsS --max-time 60 http://127.0.0.1:{http_port}/debug/break "
            ">/dev/null 2>&1 & echo __BREAK_SENT__\n"
        )
        await _wait_for_screen_contains(client, "__BREAK_SENT__", timeout_s=10)
        await _wait_for_screen_contains(tui, "PAUSED", timeout_s=25)
        (out_dir / "tui_demo_service_paused.txt").write_text(
            await _screen_text(tui), encoding="utf-8"
        )
        tui_paused_png = out_dir / "tui_demo_service_paused.png"
        _screencapture(tui_paused_png)

        # Zoom Source pane (F2) via command palette to avoid terminal-specific function key sequences.
        await _run_palette_command(tui, query="view.zoom", expect="Zoom Pane")
        # Verify by layout change (avoid depending on truncated status line).
        await _wait_for_screen_not_contains(tui, "▊ Stack", timeout_s=12)
        (out_dir / "tui_demo_service_zoomed.txt").write_text(
            await _screen_text(tui), encoding="utf-8"
        )
        tui_zoomed_png = out_dir / "tui_demo_service_zoomed.png"
        _screencapture(tui_zoomed_png)

        # Unzoom.
        await _run_palette_command(tui, query="view.zoom", expect="Zoom Pane")
        await _wait_for_screen_contains(tui, "▊ Stack", timeout_s=12)
        (out_dir / "tui_demo_service_unzoomed.txt").write_text(
            await _screen_text(tui), encoding="utf-8"
        )
        tui_unzoomed_png = out_dir / "tui_demo_service_unzoomed.png"
        _screencapture(tui_unzoomed_png)

        # Add configured breakpoints (logpoint + hit count) and verify they render in the Breakpoints pane.
        await tui.async_send_text("\x02")  # Ctrl+B
        try:
            await _wait_for_screen_contains(tui, "Add breakpoint", timeout_s=2)
        except TimeoutError:
            await _run_palette_command(tui, query="breakpoint.add", expect="Add Breakpoint")
            await _wait_for_screen_contains(tui, "Add breakpoint", timeout_s=6)
        await tui.async_send_text("examples/demo_service.py:128 log __YLOG__\r")
        await _wait_for_screen_not_contains(tui, "Add breakpoint", timeout_s=6)
        await asyncio.sleep(0.25)

        await tui.async_send_text("\x02")  # Ctrl+B
        try:
            await _wait_for_screen_contains(tui, "Add breakpoint", timeout_s=2)
        except TimeoutError:
            await _run_palette_command(tui, query="breakpoint.add", expect="Add Breakpoint")
            await _wait_for_screen_contains(tui, "Add breakpoint", timeout_s=6)
        await tui.async_send_text("examples/demo_service.py:190 hit 3\r")
        await _wait_for_screen_not_contains(tui, "Add breakpoint", timeout_s=6)
        await asyncio.sleep(0.25)

        await _wait_for_screen_contains(tui, "Breakpoints set: demo_service.py (1)", timeout_s=10)
        await _wait_for_screen_contains(tui, "Breakpoints set: demo_service.py (2)", timeout_s=10)
        (out_dir / "tui_demo_service_breakpoints_config.txt").write_text(
            await _screen_text(tui), encoding="utf-8"
        )
        tui_bp_cfg_png = out_dir / "tui_demo_service_breakpoints_config.png"
        _screencapture(tui_bp_cfg_png)

        # Ensure focus isn't inside an Input widget.
        await tui.async_send_text("\t\t")
        await asyncio.sleep(0.25)

        # Add a watch (Ctrl+W).
        await tui.async_send_text("\x17")  # Ctrl+W
        await _wait_for_screen_contains(tui, "Enter add", timeout_s=6)
        await asyncio.sleep(0.2)
        await tui.async_send_text("len(recent_jobs)\r")
        await _wait_for_screen_contains(tui, "added", timeout_s=6)
        (out_dir / "tui_demo_service_watch.txt").write_text(
            await _screen_text(tui), encoding="utf-8"
        )
        tui_watch_png = out_dir / "tui_demo_service_watch.png"
        _screencapture(tui_watch_png)

        # Close Watch.
        await tui.async_send_text("\x1b")  # Escape
        await _wait_for_screen_not_contains(tui, "Enter add", timeout_s=6)
        await asyncio.sleep(0.2)

        # Find in Source (Ctrl+F). This is intentionally tested while Source is focused.
        await tui.async_send_text("\x06")  # Ctrl+F
        await _wait_for_screen_contains(tui, "Enter next", timeout_s=6)
        await asyncio.sleep(0.2)
        await tui.async_send_text("debugpy\r")
        await asyncio.sleep(0.25)
        (out_dir / "tui_demo_service_find.txt").write_text(
            await _screen_text(tui), encoding="utf-8"
        )
        tui_find_png = out_dir / "tui_demo_service_find.png"
        _screencapture(tui_find_png)

        # Close Find.
        await tui.async_send_text("\x1b")  # Escape
        await _wait_for_screen_not_contains(tui, "Enter next", timeout_s=6)
        await asyncio.sleep(0.2)

        # Move the Source cursor away from the execution line and verify the status shows `src …`.
        # Then jump back to the execution line (Ctrl+E) and verify `src …` clears.
        await tui.async_send_text("\x07")  # Ctrl+G
        await _wait_for_screen_contains(tui, "Go to line", timeout_s=6)
        await asyncio.sleep(0.2)
        await tui.async_send_text("1:1\r")
        await _wait_for_screen_not_contains(tui, "Go to line", timeout_s=6)
        await _wait_for_screen_contains(tui, "from __future__ import annotations", timeout_s=6)
        (out_dir / "tui_demo_service_src_moved.txt").write_text(
            await _screen_text(tui), encoding="utf-8"
        )
        tui_src_moved_png = out_dir / "tui_demo_service_src_moved.png"
        _screencapture(tui_src_moved_png)

        await tui.async_send_text("\x05")  # Ctrl+E
        await _wait_for_screen_contains(tui, "debugpy.breakpoint()", timeout_s=6)
        (out_dir / "tui_demo_service_jump_to_exec.txt").write_text(
            await _screen_text(tui), encoding="utf-8"
        )
        tui_jump_to_exec_png = out_dir / "tui_demo_service_jump_to_exec.png"
        _screencapture(tui_jump_to_exec_png)

        # Step over.
        await tui.async_send_text("n")
        await _wait_for_screen_contains(tui, "Stopped (step)", timeout_s=12)
        tui_step_png = out_dir / "tui_demo_service_step.png"
        _screencapture(tui_step_png)

        # Continue.
        await tui.async_send_text("c")
        await _wait_for_screen_contains(tui, "RUNNING", timeout_s=12)
        tui_running_png = out_dir / "tui_demo_service_running.png"
        _screencapture(tui_running_png)

        # Exercise hit-condition breakpoint (3rd /health pauses).
        await client.async_send_text(
            f"curl -fsS http://127.0.0.1:{http_port}/health >/dev/null && echo __HEALTH_1_OK__\n"
        )
        await _wait_for_screen_contains(client, "__HEALTH_1_OK__", timeout_s=10)
        await client.async_send_text(
            f"curl -fsS http://127.0.0.1:{http_port}/health >/dev/null && echo __HEALTH_2_OK__\n"
        )
        await _wait_for_screen_contains(client, "__HEALTH_2_OK__", timeout_s=10)

        await client.async_send_text(
            f"curl -fsS --max-time 60 http://127.0.0.1:{http_port}/health "
            ">/dev/null 2>&1 & echo __HEALTH_3_SENT__\n"
        )
        await _wait_for_screen_contains(client, "__HEALTH_3_SENT__", timeout_s=10)
        await _wait_for_screen_contains(tui, "PAUSED", timeout_s=25)
        (out_dir / "tui_demo_service_hit3_paused.txt").write_text(
            await _screen_text(tui), encoding="utf-8"
        )
        tui_hit3_png = out_dir / "tui_demo_service_hit3_paused.png"
        _screencapture(tui_hit3_png)

        await tui.async_send_text("c")
        await _wait_for_screen_contains(tui, "RUNNING", timeout_s=12)

        print(f"Wrote {demo_png}")
        print(f"Wrote {tui_main_png}")
        print(f"Wrote {tui_connected_png}")
        print(f"Wrote {tui_paused_png}")
        print(f"Wrote {tui_zoomed_png}")
        print(f"Wrote {tui_unzoomed_png}")
        print(f"Wrote {tui_bp_cfg_png}")
        print(f"Wrote {tui_watch_png}")
        print(f"Wrote {tui_find_png}")
        print(f"Wrote {tui_src_moved_png}")
        print(f"Wrote {tui_jump_to_exec_png}")
        print(f"Wrote {tui_step_png}")
        print(f"Wrote {tui_running_png}")
        print(f"Wrote {tui_hit3_png}")
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
