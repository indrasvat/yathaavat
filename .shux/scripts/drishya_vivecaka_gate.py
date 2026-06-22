#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# ///

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / ".shux" / "out"
SMOKE = ROOT / ".shux" / "scripts" / "inspector2_smoke.py"
REQUIRED_SCREENSHOTS = (
    "inspector2-01-paused-locals.png",
    "inspector2-02-globals-scope.png",
    "inspector2-03-globals-after-update.png",
    "inspector2-04-expanded-page.png",
    "inspector2-05-load-more.png",
    "inspector2-06-filtered.png",
    "inspector2-07-edit-dialog.png",
    "inspector2-08-edit-result.png",
)


def main() -> int:
    require_command("make", "The Dṛśya-Vivecaka gate delegates to the repo CI target.")
    require_command("shux", "The Dṛśya-Vivecaka gate requires shux visual automation.")
    checks: list[dict[str, Any]] = []
    ok = True

    ci = run(["make", "ci"])
    checks.append(result("make ci", ci))
    ok = ok and ci.returncode == 0

    smoke = run(["uv", "run", "--script", str(SMOKE)])
    checks.append(result("shux inspector2 smoke", smoke))
    ok = ok and smoke.returncode == 0

    screenshot_checks = verify_screenshots()
    checks.extend(screenshot_checks)
    ok = ok and all(check["status"] == "PASS" for check in screenshot_checks)

    report = {
        "gate": "Dṛśya-Vivecaka",
        "transliteration": "drishya-vivecaka",
        "status": "PASS" if ok else "FAIL",
        "checks": checks,
    }
    print(json.dumps(report, indent=2))
    return 0 if ok else 1


def run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, text=True, capture_output=True, check=False)


def require_command(command: str, message: str) -> None:
    if shutil.which(command) is None:
        raise SystemExit(f"Missing required command: {command}. {message}")


def result(name: str, completed: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    return {
        "name": name,
        "status": "PASS" if completed.returncode == 0 else "FAIL",
        "returncode": completed.returncode,
        "stdout_tail": tail(completed.stdout),
        "stderr_tail": tail(completed.stderr),
    }


def verify_screenshots() -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for name in REQUIRED_SCREENSHOTS:
        path = OUT / name
        if not path.exists():
            checks.append({"name": f"screenshot {name}", "status": "FAIL", "reason": "missing"})
            continue
        try:
            width, height = png_dimensions(path)
        except ValueError as exc:
            checks.append({"name": f"screenshot {name}", "status": "FAIL", "reason": str(exc)})
            continue
        size = path.stat().st_size
        checks.append(
            {
                "name": f"screenshot {name}",
                "status": "PASS" if width >= 1200 and height >= 700 and size > 10_000 else "FAIL",
                "width": width,
                "height": height,
                "bytes": size,
            }
        )
    return checks


def png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()[:24]
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise ValueError("not a valid PNG")
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    return width, height


def tail(text: str, *, lines: int = 12) -> str:
    parts = text.strip().splitlines()
    return "\n".join(parts[-lines:])


if __name__ == "__main__":
    sys.exit(main())
