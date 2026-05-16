from __future__ import annotations

import subprocess
import sys

import pytest

from tests.support import RecordingHost, RecordingManager, make_context
from yathaavat.app import attach
from yathaavat.core.processes import ProcessInfo


def test_attach_endpoint_parsers_and_safe_attach_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    assert attach._truncate("abcdef", 4) == "abc…"
    assert attach._debugpy_dap_endpoint("python -m debugpy --listen 5678 app.py") == (
        "127.0.0.1",
        5678,
    )
    assert attach._debugpy_dap_endpoint("debugpy --listen localhost:9000 app.py") == (
        "localhost",
        9000,
    )
    assert attach._debugpy_dap_endpoint("debugpy --listen bad") is None
    assert attach._debugpy_adapter_endpoint("python -m debugpy.adapter --host ::1 --port 4711") == (
        "::1",
        4711,
    )
    assert attach._debugpy_adapter_endpoint("python app.py") is None
    assert attach._is_loopback("[::1]") is True
    assert attach._is_loopback("10.0.0.2") is False

    monkeypatch.delattr(sys, "remote_exec", raising=False)
    assert attach._safe_attach_unavailable_reason() == "unsupported locally"
    monkeypatch.setattr(sys, "remote_exec", object(), raising=False)
    monkeypatch.setenv("PYTHON_DISABLE_REMOTE_DEBUG", "1")
    assert attach._safe_attach_unavailable_reason() == "disabled locally"


def test_attach_lsof_parsers_ignore_bad_process_output(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if "-sTCP:LISTEN" in cmd and "-t" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="101\nbad\n202\n", stderr="")
        if "-sTCP:LISTEN" in cmd:
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout=(
                    "COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME\n"
                    "python 1 me 3u IPv4 TCP *:5678 (LISTEN)\n"
                    "python 1 me 4u IPv6 TCP [::1]:9000 (LISTEN)\n"
                    "python 1 me 5u IPv4 TCP bad:port (LISTEN)\n"
                ),
                stderr="",
            )
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=(
                "python 1 me 3u IPv4 TCP 127.0.0.1:5000->127.0.0.1:6000 (ESTABLISHED)\n"
                "python 1 me 4u IPv4 TCP 127.0.0.1:5001->10.0.0.2:6001 (ESTABLISHED)\n"
                "python 1 me 5u IPv4 TCP bad\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert attach._list_listening_tcp_endpoints(123) == [("127.0.0.1", 5678), ("::1", 9000)]
    assert attach._list_established_remote_ports(123) == [6000]
    assert attach._listener_pids_for_port(6000) == [101, 202]


def test_attach_picker_rows_mark_debugpy_and_safe_attach_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(attach, "_safe_attach_unavailable_reason", lambda: None)
    ctx = make_context(manager=RecordingManager(), host=RecordingHost())
    picker = attach.AttachPicker(ctx=ctx)
    picker._processes = [
        ProcessInfo(
            pid=2, command="python", args="python -m debugpy --listen 5678 app.py", is_python=True
        ),
        ProcessInfo(
            pid=3,
            command="python3.14",
            args="python3.14 worker.py",
            is_python=True,
            python_version_hint="3.14",
        ),
        ProcessInfo(pid=4, command="node", args="node server.js", is_python=False),
    ]

    rows = picker._rows()
    assert [(row.pid, row.dap_endpoint, row.safe_attach_enabled) for row in rows] == [
        (2, ("127.0.0.1", 5678), False),
        (3, None, True),
    ]

    picker.show_non_python = True
    picker.query_text = "node"
    assert [row.pid for row in picker._rows()] == [4]
