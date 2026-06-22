#!/usr/bin/env python3
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def check(name: str, ok: bool, detail: str = "") -> bool:
    status = "OK" if ok else "FAIL"
    suffix = f" - {detail}" if detail else ""
    print(f"{status:4} {name}{suffix}")
    return ok


def run(argv: list[str]) -> tuple[bool, str]:
    try:
        out = subprocess.run(argv, text=True, capture_output=True, timeout=10, check=False)
    except Exception as exc:
        return False, str(exc)
    text = (out.stdout or out.stderr).strip().splitlines()
    return out.returncode == 0, text[0] if text else ""


def main() -> int:
    root = Path.cwd()
    ok = True
    ok &= check(
        "repo root", (root / "pyproject.toml").exists() and (root / "src/yathaavat").exists()
    )
    ok &= check("uv", shutil.which("uv") is not None)
    ok &= check("shux", shutil.which("shux") is not None)
    cmd_ok, detail = run(["uv", "run", "--python", "python3.14", "yathaavat", "--help"])
    ok &= check("yathaavat help", cmd_ok, detail)
    cmd_ok, detail = run(["shux", "--version"])
    ok &= check("shux version", cmd_ok, detail)
    tmp_root = Path("/tmp/yathaavat-gauntlet")
    try:
        tmp_root.mkdir(parents=True, exist_ok=True)
        tmp_ok = tmp_root.is_dir()
    except OSError:
        tmp_ok = False
    ok &= check("tmp gauntlet root", tmp_ok, str(tmp_root))
    print()
    print("Use /tmp/yathaavat-gauntlet/<slug>/target for generated apps.")
    print("Use /tmp/yathaavat-gauntlet/<slug>/evidence for shux screenshots and captures.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
