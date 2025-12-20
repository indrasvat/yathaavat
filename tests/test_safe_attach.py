from __future__ import annotations

import asyncio
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest

from yathaavat.core import NullUiHost, SessionStore
from yathaavat.plugins.debugpy import DebugpySessionManager, _remote_exec_script


def test_remote_exec_script_contains_required_fields() -> None:
    status = Path("/tmp/yathaavat_status.json")
    script = _remote_exec_script(status_path=status, host="127.0.0.1", port=5678)
    assert "debugpy.listen" in script
    assert str(status) in script
    assert "5678" in script


def test_await_remote_exec_status_errors_fast() -> None:
    async def main(tmp_path: Path) -> None:
        status = tmp_path / "status.json"
        status.write_text(json.dumps({"state": "error", "error": "boom"}), encoding="utf-8")
        mgr = DebugpySessionManager(store=SessionStore(), host=NullUiHost())
        with pytest.raises(RuntimeError, match="boom"):
            await mgr._await_remote_exec_status(status, timeout_s=0.5)

    with tempfile.TemporaryDirectory() as td:
        asyncio.run(main(Path(td)))


def test_await_remote_exec_status_listening_returns() -> None:
    async def main(tmp_path: Path) -> None:
        status = tmp_path / "status.json"
        status.write_text(json.dumps({"state": "listening"}), encoding="utf-8")
        mgr = DebugpySessionManager(store=SessionStore(), host=NullUiHost())
        await mgr._await_remote_exec_status(status, timeout_s=0.5)

    with tempfile.TemporaryDirectory() as td:
        asyncio.run(main(Path(td)))


def test_pid_attach_timeout_adds_transcript(monkeypatch: pytest.MonkeyPatch) -> None:
    async def main() -> None:
        store = SessionStore()
        mgr = DebugpySessionManager(store=store, host=NullUiHost())

        def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            timeout = float(kwargs.get("timeout", 0))
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout, output=b"", stderr=b"boom")

        monkeypatch.setattr(subprocess, "run", fake_run)

        with pytest.raises(TimeoutError, match="PID attach timed out"):
            await mgr.attach(12345)

        transcript = "\n".join(store.snapshot().transcript)
        assert "PID attach timed out" in transcript
        assert "boom" in transcript

    asyncio.run(main())
