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

    http_port = _pick_free_port()
    dap_port = _pick_free_port()

    # --- Start demo service in a fresh tab ---
    service_tab = await window.async_create_tab()
    service = service_tab.current_session
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
    (out_dir / "demo_service_running.txt").write_text(await _screen_text(service), encoding="utf-8")
    demo_png = out_dir / "demo_service_running.png"
    _screencapture(demo_png)

    # --- Start yathaavat in a separate tab ---
    tui_tab = await window.async_create_tab()
    tui = tui_tab.current_session
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
    (out_dir / "tui_demo_service_paused.txt").write_text(await _screen_text(tui), encoding="utf-8")
    tui_paused_png = out_dir / "tui_demo_service_paused.png"
    _screencapture(tui_paused_png)

    # Add configured breakpoints (logpoint + hit count) and verify they render in the Breakpoints pane.
    await tui.async_send_text("\x02")  # Ctrl+B
    await _wait_for_screen_contains(tui, "Add breakpoint", timeout_s=6)
    await asyncio.sleep(0.2)
    await tui.async_send_text("examples/demo_service.py:128 log __YLOG__\r")
    await _wait_for_screen_not_contains(tui, "Add breakpoint", timeout_s=6)
    await asyncio.sleep(0.25)

    await tui.async_send_text("\x02")  # Ctrl+B
    await _wait_for_screen_contains(tui, "Add breakpoint", timeout_s=6)
    await asyncio.sleep(0.2)
    await tui.async_send_text("examples/demo_service.py:190 hit 3\r")
    await _wait_for_screen_not_contains(tui, "Add breakpoint", timeout_s=6)
    await asyncio.sleep(0.25)

    await _wait_for_screen_contains(tui, "__YLOG__", timeout_s=6)
    await _wait_for_screen_contains(tui, "hit 3", timeout_s=6)
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
    (out_dir / "tui_demo_service_watch.txt").write_text(await _screen_text(tui), encoding="utf-8")
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
    (out_dir / "tui_demo_service_find.txt").write_text(await _screen_text(tui), encoding="utf-8")
    tui_find_png = out_dir / "tui_demo_service_find.png"
    _screencapture(tui_find_png)

    # Close Find.
    await tui.async_send_text("\x1b")  # Escape
    await _wait_for_screen_not_contains(tui, "Enter next", timeout_s=6)
    await asyncio.sleep(0.2)

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

    # Quit yathaavat.
    await tui.async_send_text("\x11")  # Ctrl+Q
    await asyncio.sleep(0.6)

    # Stop the service.
    await service.async_send_text("\x03")  # Ctrl+C
    await asyncio.sleep(0.4)

    print(f"Wrote {demo_png}")
    print(f"Wrote {tui_main_png}")
    print(f"Wrote {tui_connected_png}")
    print(f"Wrote {tui_paused_png}")
    print(f"Wrote {tui_bp_cfg_png}")
    print(f"Wrote {tui_watch_png}")
    print(f"Wrote {tui_find_png}")
    print(f"Wrote {tui_step_png}")
    print(f"Wrote {tui_running_png}")
    print(f"Wrote {tui_hit3_png}")


if __name__ == "__main__":
    iterm2.run_until_complete(main)
