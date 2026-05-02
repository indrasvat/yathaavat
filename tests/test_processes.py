from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from yathaavat.core.processes import ProcessInfo
from yathaavat.plugins.processes import (
    _args_disable_remote_debug,
    _enrich_python_process,
    _probe_python_version_hint,
    parse_ps_output,
)


def test_parse_ps_output_flags_python_processes() -> None:
    out = parse_ps_output(
        "  123 python3.14 python3.14 -m myapp\n"
        "  124 bash bash -lc echo hi\n"
        "  125 Python Python -c print('x')\n"
        "  126 /opt/homebrew/Ce /opt/homebrew/Cellar/python@3.14/3.14.2/bin/python3.14 -c 1\n"
    )
    by_pid = {p.pid: p for p in out}
    assert by_pid[123].is_python is True
    assert by_pid[124].is_python is False
    assert by_pid[125].is_python is True
    assert by_pid[126].is_python is True


def test_parse_ps_output_extracts_version_hint() -> None:
    out = parse_ps_output("  123 python3.14 python3.14 -m myapp\n")
    assert out[0].python_version_hint == "3.14"

    out = parse_ps_output(
        "  126 /opt/homebrew/Ce /opt/homebrew/Cellar/python@3.14/3.14.2/bin/python3.14 -c 1\n"
    )
    assert out[0].python_version_hint == "3.14"


def test_parse_ps_output_uses_args_argv0_for_display_command() -> None:
    out = parse_ps_output(
        "  126 /opt/homebrew/Ce /opt/homebrew/Cellar/python@3.14/3.14.2/bin/python3.14 -c 1\n"
    )
    assert out[0].command == "python3.14"


def test_probe_python_version_hint_uses_proc_exe(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeCompleted:
        returncode = 0
        stdout = "3.14\n"

    def fake_exists(path: Path) -> bool:
        return str(path) == "/proc/123/exe"

    def fake_run(cmd: list[str], **kwargs: Any) -> FakeCompleted:
        assert cmd[:4] == ["/proc/123/exe", "-I", "-S", "-c"]
        assert kwargs["timeout"] == 1.5
        return FakeCompleted()

    monkeypatch.setattr(Path, "exists", fake_exists)
    monkeypatch.setattr(subprocess, "run", fake_run)

    assert _probe_python_version_hint(123) == "3.14"


def test_enrich_python_process_probes_plain_python_and_remote_debug_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeCompleted:
        returncode = 0
        stdout = "3.14\n"

    def fake_exists(path: Path) -> bool:
        return str(path) == "/proc/123/exe"

    def fake_read_bytes(path: Path) -> bytes:
        assert str(path) == "/proc/123/environ"
        return b"USER=dev\0PYTHON_DISABLE_REMOTE_DEBUG=1\0"

    def fake_run(_cmd: list[str], **_kwargs: Any) -> FakeCompleted:
        return FakeCompleted()

    monkeypatch.setattr(Path, "exists", fake_exists)
    monkeypatch.setattr(Path, "read_bytes", fake_read_bytes)
    monkeypatch.setattr(subprocess, "run", fake_run)

    proc = ProcessInfo(
        pid=123,
        command="python",
        args="python -m service",
        is_python=True,
    )
    enriched = _enrich_python_process(proc)

    assert enriched.python_version_hint == "3.14"
    assert enriched.remote_debug_disabled is True


def test_args_disable_remote_debug_detects_python_x_option() -> None:
    assert _args_disable_remote_debug("python -X disable_remote_debug -m service") is True
    assert _args_disable_remote_debug("python -Xdisable_remote_debug -m service") is True
    assert _args_disable_remote_debug("python -m service") is False
