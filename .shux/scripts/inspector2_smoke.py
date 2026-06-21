#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# ///

from __future__ import annotations

import base64
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / ".shux" / "out"
SESSION = "yathaavat-inspector2-smoke"
CTRL_R = "Eg=="
CTRL_P = "EA=="
ENTER = "DQ=="
ESC = "Gw=="
DOWN = "G1tC"


def main() -> int:
    require_command("shux", "Install shux before running the Inspector 2.0 visual smoke.")
    OUT.mkdir(parents=True, exist_ok=True)
    run(["shux", "session", "kill", SESSION], check=False)

    created = run_json(
        [
            "shux",
            "--format",
            "json",
            "session",
            "create",
            SESSION,
            "-d",
            "--title",
            "inspector2",
            "--",
            "env",
            "-u",
            "NO_COLOR",
            "TERM=xterm-256color",
            "COLORTERM=truecolor",
            "FORCE_COLOR=1",
            "YATHAAVAT_VARIABLE_PAGE_SIZE=8",
            "uv",
            "run",
            "--python",
            "python3.14",
            "yathaavat",
        ]
    )
    pane = str(created["pane_id"])

    try:
        run(
            [
                "shux",
                "pane",
                "set-size",
                "-s",
                SESSION,
                "--pane",
                pane,
                "--cols",
                "160",
                "--rows",
                "48",
            ]
        )
        wait_for(pane, "yathaavat")

        send_data(pane, CTRL_R)
        wait_for(pane, "Launch under debugpy")
        send_text(pane, "examples/demo_inspector.py")
        send_data(pane, ENTER)
        wait_for(pane, "PAUSED", timeout_ms=15000)
        wait_for(pane, "box", timeout_ms=10000)
        snapshot(pane, "inspector2-01-paused-locals.png")
        assert_screen(pane, "filter locals")

        focus_locals(pane)
        send_data(pane, DOWN)
        run_palette_command(pane, "expand selected local", "Expand Selected Local")
        snapshot(pane, "inspector2-debug-after-expand-key.png")
        wait_for(pane, "Load more")
        snapshot(pane, "inspector2-02-expanded-page.png")

        focus_locals(pane)
        for _ in range(10):
            send_data(pane, DOWN)
        run_palette_command(pane, "expand selected local", "Expand Selected Local")
        wait_for(pane, "item-013")
        snapshot(pane, "inspector2-03-load-more.png")

        run_palette_command(pane, "filter locals", "Filter Locals")
        send_text(pane, "013")
        time.sleep(0.4)
        wait_for(pane, "item-013")
        snapshot(pane, "inspector2-04-filtered.png")

        send_data(pane, ENTER)
        send_data(pane, DOWN)
        run_palette_command(pane, "edit selected local", "Edit Selected Local")
        wait_for(pane, "Edit")
        snapshot(pane, "inspector2-05-edit-dialog.png")

        send_text(pane, "'changed'")
        send_data(pane, ENTER)
        wait_for(pane, "changed")
        snapshot(pane, "inspector2-06-edit-result.png")

        print(
            json.dumps(
                {
                    "session": SESSION,
                    "pane": pane,
                    "screenshots": sorted(p.name for p in OUT.glob("inspector2-*.png")),
                },
                indent=2,
            )
        )
        return 0
    finally:
        run(["shux", "session", "kill", SESSION], check=False)


def run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, text=True, capture_output=True, check=check)


def require_command(command: str, message: str) -> None:
    if shutil.which(command) is None:
        raise SystemExit(f"Missing required command: {command}. {message}")


def run_json(args: list[str]) -> dict[str, Any]:
    completed = run(args)
    return json.loads(completed.stdout)


def wait_for(pane: str, text: str, *, timeout_ms: int = 5000) -> None:
    run(
        [
            "shux",
            "pane",
            "wait-for",
            "-s",
            SESSION,
            "--pane",
            pane,
            "--text",
            text,
            "--timeout-ms",
            str(timeout_ms),
        ]
    )


def send_text(pane: str, text: str) -> None:
    run(["shux", "pane", "send-keys", "-s", SESSION, "--pane", pane, "--text", text])


def send_data(pane: str, data: str) -> None:
    run(["shux", "pane", "send-keys", "-s", SESSION, "--pane", pane, "--data", data])


def focus_locals(pane: str) -> None:
    run_palette_command(pane, "focus locals", "Focus Locals")
    wait_for(pane, "box")


def run_palette_command(pane: str, query: str, result: str) -> None:
    send_data(pane, CTRL_P)
    wait_for(pane, "Command Palette")
    send_text(pane, query)
    wait_for(pane, result)
    send_data(pane, ENTER)
    time.sleep(0.6)


def snapshot(pane: str, filename: str) -> None:
    payload = run_json(
        ["shux", "--format", "json", "pane", "snapshot", "-s", SESSION, "--pane", pane]
    )
    png = base64.b64decode(str(payload["png_base64"]))
    (OUT / filename).write_bytes(png)


def assert_screen(pane: str, needle: str) -> None:
    completed = run(["shux", "pane", "capture", "-s", SESSION, "--pane", pane])
    if needle not in completed.stdout:
        raise AssertionError(f"expected {needle!r} in pane capture")


if __name__ == "__main__":
    sys.exit(main())
