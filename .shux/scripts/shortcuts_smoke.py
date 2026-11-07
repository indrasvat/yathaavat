#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# ///
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / ".shux" / "out" / "shortcuts"
SESSION = "shortcuts-evidence"


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify the real yathaavat shortcuts UI with shux")
    parser.add_argument("--record", action="store_true", help="Also capture a 30 second MP4")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    runtime = tempfile.mkdtemp(prefix="ys-", dir="/tmp")
    env = {**os.environ, "XDG_RUNTIME_DIR": runtime}

    def run(*argv: str) -> str:
        return subprocess.run(
            argv, cwd=ROOT, env=env, check=True, text=True, capture_output=True
        ).stdout

    def shux(*argv: str) -> str:
        return run("shux", *argv)

    pane = ""

    def settle() -> None:
        shux("pane", "wait-settled", pane, "--quiet", "400ms", "--timeout", "10s")

    def send(text: str) -> None:
        shux("pane", "send-keys", "-s", SESSION, "--text", text)

    def key(data: bytes) -> None:
        shux("pane", "send-keys", "-s", SESSION, "--data", base64.b64encode(data).decode())

    def wait(text: str, *, absent: bool = False, timeout_ms: int = 30000) -> None:
        flags = ("--absent",) if absent else ()
        try:
            shux(
                "pane",
                "wait-for",
                "-s",
                SESSION,
                "--text",
                text,
                "--timeout-ms",
                str(timeout_ms),
                *flags,
            )
        except subprocess.CalledProcessError:
            snapshot("failure.png")
            raise

    def capture() -> str:
        return shux("pane", "capture", "-s", SESSION)

    def snapshot(name: str) -> None:
        shux("pane", "snapshot", "-s", SESSION, "-o", str(OUT / name))
        (OUT / name.replace(".png", ".txt")).write_text(capture())

    def size(cols: int, rows: int) -> None:
        shux("pane", "set-size", "-s", SESSION, "--cols", str(cols), "--rows", str(rows))

    def palette(query: str, expected: str) -> None:
        key(b"\x10")
        wait("Command Palette")
        send(query)
        wait(expected)
        settle()
        key(b"\r")

    try:
        created = shux(
            "--format",
            "json",
            "session",
            "create",
            SESSION,
            "-d",
            "--",
            "env",
            "-u",
            "NO_COLOR",
            "TERM=xterm-256color",
            "COLORTERM=truecolor",
            "FORCE_COLOR=1",
            "uv",
            "run",
            "--frozen",
            "yathaavat",
        )
        pane = json.loads(created)["pane_id"]
        size(160, 46)
        wait("yathaavat")
        if args.record:
            key(b"\x12")
            wait("Launch under debugpy")
            send("examples/demo_inspector.py")
            wait("examples/demo_inspector.py")
            settle()
            key(b"\r")
            wait("PAUSED", timeout_ms=60000)
            settle()
            wait("box")
            settle()
            wait("PAUSED", timeout_ms=60000)
        snapshot("01-debugger.png")

        def open_overlay() -> None:
            send("?")
            wait("Keyboard shortcuts")
            snapshot("02-overlay.png")

        def scroll_down() -> None:
            key(b"\x1b[6~")
            wait("Add Watch…")
            snapshot("03-scrolled.png")

        def scroll_up() -> None:
            key(b"\x1b[5~")
            wait("Application")

        def close_overlay() -> None:
            key(b"\x1b")
            wait("Keyboard shortcuts", absent=True)
            snapshot("04-closed.png")

        def open_find() -> None:
            send("/")
            wait("Enter next")

        def type_question() -> None:
            send("?")
            wait("No matches" if args.record else "No source text loaded.")
            assert "Keyboard shortcuts" not in capture()
            assert "?" in capture()
            snapshot("05-find-question.png")

        actions = [
            (4, open_overlay),
            (12, scroll_down),
            (16, scroll_up),
            (20, close_overlay),
            (23, open_find),
            (25, type_question),
        ]
        if args.record:
            frames = OUT / "frames"
            frames.mkdir(exist_ok=True)
            start = time.monotonic()
            for index in range(60):
                deadline = start + index / 2
                time.sleep(max(0, deadline - time.monotonic()))
                while actions and actions[0][0] <= index / 2:
                    actions.pop(0)[1]()
                shux("pane", "snapshot", "-s", SESSION, "-o", str(frames / f"{index:03}.png"))
            run(
                "ffmpeg",
                "-y",
                "-framerate",
                "2",
                "-i",
                str(frames / "%03d.png"),
                "-c:v",
                "libx264",
                "-threads",
                "2",
                "-preset",
                "ultrafast",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                "-r",
                "2",
                "-movflags",
                "+faststart",
                str(OUT / "shortcuts-demo.mp4"),
            )
        else:
            for _, action in actions:
                action()

        # The find field accepts '?'; Esc returns focus to Source.
        key(b"\x1b")
        settle()
        wait("No matches", absent=True)
        size(80, 24)
        send("?")
        wait("Keyboard shortcuts")
        snapshot("06-compact.png")
        key(b"\x1b[F")
        wait("Add Watch…")
        snapshot("06-compact-scrolled.png")
        send("?")
        wait("Keyboard shortcuts", absent=True)
        size(160, 46)

        # Palette input must keep '?', and the Help command must open the overlay.
        key(b"\x10")
        wait("Command Palette")
        send("?")
        assert "Keyboard shortcuts" not in capture()
        wait("?")
        snapshot("07-palette-question.png")
        key(b"\x1b")
        wait("Command Palette", absent=True)
        palette("Help: keyboard shortcuts", "Help: keyboard shortcuts")
        wait("Keyboard shortcuts")
        key(b"\x1b")
        wait("Keyboard shortcuts", absent=True)

        key(b"\x17")
        wait("Add Watch")
        send("?")
        wait("?")
        assert "Keyboard shortcuts" not in capture()
        snapshot("08-watch-question.png")
        key(b"\x1b")
        wait("Add Watch", absent=True)

        # App-level punctuation bindings must work outside Source too.
        key(b"\x0c")
        settle()
        send("?")
        wait("Keyboard shortcuts")
        key(b"\x1b")
        wait("Keyboard shortcuts", absent=True)
        send("/")
        send("locals_probe?")
        wait("locals_probe?")
        assert "Keyboard shortcuts" not in capture()
        snapshot("09-locals-filter-question.png")
        print(json.dumps({"status": "PASS", "artifacts": str(OUT), "recorded": args.record}))
    finally:
        subprocess.run(
            ["shux", "session", "kill", SESSION], env=env, capture_output=True, check=False
        )
        subprocess.run(["shux", "daemon", "stop"], env=env, capture_output=True, check=False)
        shutil.rmtree(runtime, ignore_errors=True)


if __name__ == "__main__":
    main()
