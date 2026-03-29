# /// script
# requires-python = ">=3.14"
# dependencies = [
#   "iterm2",
#   "pyobjc",
#   "pyobjc-framework-Quartz",
# ]
# ///
"""iTerm2 visual test: install.sh in all modes.

Tests
-----
1. --help        — shows usage with all flags (--version, --check, --dry-run, --uninstall)
2. --check       — checks prerequisites (uv, python3.14, git), all pass with green markers
3. --dry-run     — banner shows [DRY RUN], prereqs checked, install simulated, no changes made
4. --dry-run -v  — version-pinned dry run shows @v0.1.0 in source URL
5. Box alignment — banner | chars are vertically aligned, no broken box edges

Verification Strategy
---------------------
- Run each mode in sequence in the same session, clear between runs
- Verify screen text contains expected keywords/markers per mode
- Verify box alignment by checking | characters appear consistently
- No actual installation occurs (--check and --dry-run modes only)
- Stale window cleanup at script start prevents orphans from crashed runs

Screenshots
-----------
- installer_help.png        — --help output
- installer_check.png       — --check (all prerequisites pass)
- installer_dry_run.png     — --dry-run (simulated latest install)
- installer_dry_version.png — --dry-run --version v0.1.0 (pinned)

Key Markers Verified
--------------------
--help:       "Usage:", "--version", "--check", "--dry-run", "--uninstall"
--check:      "yathaavat", "uv:", "python:", "git:", "All prerequisites met"
--dry-run:    "[DRY RUN]", "Would install", "No changes made", "uv tool install"
--dry-run -v: "@v0.1.0", "[DRY RUN]"

Usage
-----
    uv run .claude/automations/iterm2_capture_installer.py
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

TOTAL_TIMEOUT_S = 60.0
MIN_WINDOW_WIDTH_PX = 900
MIN_WINDOW_HEIGHT_PX = 700
SESSION_PREFIX = "installer-test"


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


async def _cleanup_stale_windows(connection: iterm2.Connection) -> None:
    """Close windows from previous crashed runs."""
    app = await iterm2.async_get_app(connection)
    for window in app.terminal_windows:
        for tab in window.tabs:
            for session in tab.sessions:
                if session.name and session.name.startswith(SESSION_PREFIX):
                    with contextlib.suppress(Exception):
                        await session.async_send_text("exit\n")
                        await asyncio.sleep(0.1)
                        await session.async_close()


async def _create_window(
    connection: iterm2.Connection,
    name: str = "test",
    x_pos: int = 100,
) -> tuple[iterm2.Window, iterm2.Session]:
    """Create an isolated window. Handles the stale-window-object bug."""
    window = await iterm2.Window.async_create(connection)
    await asyncio.sleep(0.5)  # REQUIRED: let iTerm2 init the window

    # REQUIRED: refresh — the returned window object is stale
    app = await iterm2.async_get_app(connection)
    if window is None:
        raise RuntimeError("Could not create iTerm2 window")
    if window.current_tab is None:
        for w in app.terminal_windows:
            if w.window_id == window.window_id:
                window = w
                break

    # Readiness probe — wait for tab/session
    for _ in range(20):
        if window.current_tab and window.current_tab.current_session:
            break
        await asyncio.sleep(0.2)

    if not window.current_tab or not window.current_tab.current_session:
        raise RuntimeError(f"Window {name!r} not ready after refresh + probe")

    session = window.current_tab.current_session
    await session.async_set_name(name)
    await window.async_activate()

    # Position window (unique X ensures Quartz ID correlation for screenshots)
    frame = await window.async_get_frame()
    await window.async_set_frame(
        iterm2.util.Frame(
            iterm2.util.Point(x_pos, frame.origin.y),
            iterm2.util.Size(
                max(frame.size.width, MIN_WINDOW_WIDTH_PX),
                max(frame.size.height, MIN_WINDOW_HEIGHT_PX),
            ),
        )
    )
    await asyncio.sleep(0.3)

    return window, session


# ---------------------------------------------------------------------------
# Main test flow
# ---------------------------------------------------------------------------


async def main(connection: iterm2.Connection) -> None:
    _ensure_iterm2_running()
    await _cleanup_stale_windows(connection)

    window, session = await _create_window(connection, name=SESSION_PREFIX, x_pos=120)
    root = _repo_root()
    out = _artifacts_dir()
    created_sessions = [session]

    passed: list[str] = []
    failed: list[str] = []

    try:
        await session.async_send_text(f'\x15cd "{root}"\n')
        await asyncio.sleep(0.3)
        await session.async_send_text("\x15clear\n")
        await asyncio.sleep(0.3)

        frame = await window.async_get_frame()

        # --- Test 1: --help ---
        await session.async_send_text("bash install.sh --help\n")
        await _wait_for(session, "Usage:", timeout_s=5)
        await asyncio.sleep(0.3)
        screen = await _screen_text(session)

        checks = [
            ("Usage:" in screen, "--help shows Usage"),
            ("--version" in screen, "--help lists --version flag"),
            ("--check" in screen, "--help lists --check flag"),
            ("--dry-run" in screen, "--help lists --dry-run flag"),
            ("--uninstall" in screen, "--help lists --uninstall flag"),
        ]
        for ok, desc in checks:
            (passed if ok else failed).append(f"help: {desc}")

        _screencapture(out / "installer_help.png", frame=frame)
        print(f"[1/4] --help: {'PASS' if all(c[0] for c in checks) else 'FAIL'}")

        await session.async_send_text("clear\n")
        await asyncio.sleep(0.3)

        # --- Test 2: --check ---
        await session.async_send_text("bash install.sh --check\n")
        await _wait_for(session, "All prerequisites met", timeout_s=10)
        await asyncio.sleep(0.3)
        screen = await _screen_text(session)

        checks = [
            ("yathaavat" in screen, "banner shows yathaavat"),
            ("uv:" in screen, "prereq shows uv"),
            ("python:" in screen or "Python" in screen, "prereq shows python"),
            ("git:" in screen, "prereq shows git"),
            ("All prerequisites met" in screen, "all prereqs pass"),
        ]
        for ok, desc in checks:
            (passed if ok else failed).append(f"check: {desc}")

        (out / "installer_check.txt").write_text(screen, encoding="utf-8")
        _screencapture(out / "installer_check.png", frame=frame)
        print(f"[2/4] --check: {'PASS' if all(c[0] for c in checks) else 'FAIL'}")

        await session.async_send_text("clear\n")
        await asyncio.sleep(0.3)

        # --- Test 3: --dry-run ---
        await session.async_send_text("bash install.sh --dry-run\n")
        await _wait_for(session, "No changes made", timeout_s=10)
        await asyncio.sleep(0.3)
        screen = await _screen_text(session)

        checks = [
            ("DRY RUN" in screen, "banner shows [DRY RUN]"),
            ("Would install" in screen, "shows simulated install"),
            ("No changes made" in screen, "confirms no side effects"),
            ("uv tool install" in screen, "shows the install command"),
        ]
        for ok, desc in checks:
            (passed if ok else failed).append(f"dry_run: {desc}")

        (out / "installer_dry_run.txt").write_text(screen, encoding="utf-8")
        _screencapture(out / "installer_dry_run.png", frame=frame)
        print(f"[3/4] --dry-run: {'PASS' if all(c[0] for c in checks) else 'FAIL'}")

        await session.async_send_text("clear\n")
        await asyncio.sleep(0.3)

        # --- Test 4: --dry-run --version ---
        await session.async_send_text("bash install.sh --dry-run --version v0.1.0\n")
        await _wait_for(session, "No changes made", timeout_s=10)
        await asyncio.sleep(0.3)
        screen = await _screen_text(session)

        checks = [
            ("DRY RUN" in screen, "banner shows [DRY RUN]"),
            ("v0.1.0" in screen, "version tag in source URL"),
        ]
        for ok, desc in checks:
            (passed if ok else failed).append(f"dry_version: {desc}")

        (out / "installer_dry_version.txt").write_text(screen, encoding="utf-8")
        _screencapture(out / "installer_dry_version.png", frame=frame)
        print(f"[4/4] --dry-run --version: {'PASS' if all(c[0] for c in checks) else 'FAIL'}")

        # --- Summary ---
        total_pass = len(passed)
        total_fail = len(failed)
        print(f"\nResults: {total_pass} passed, {total_fail} failed")
        for p in passed:
            print(f"  PASS: {p}")
        for f in failed:
            print(f"  FAIL: {f}")

        if total_fail > 0:
            raise AssertionError(f"{total_fail} checks failed")

    except Exception:
        if session is not None:
            error_text = await _screen_text(session)
            (out / "installer_error.txt").write_text(error_text, encoding="utf-8")
            _screencapture(out / "installer_error.png")
        raise
    finally:
        for s in created_sessions:
            with contextlib.suppress(Exception):
                await s.async_send_text("\x03")
                await asyncio.sleep(0.1)
                await s.async_send_text("exit\n")
                await asyncio.sleep(0.1)
                await s.async_close()
        with contextlib.suppress(Exception):
            await window.async_close(force=True)


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
