from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.support import RecordingHost, make_context
from yathaavat.app.attach import AttachPicker
from yathaavat.core.processes import PROCESS_DISCOVERY, ProcessDiscovery, ProcessInfo
from yathaavat.plugins.processes import (
    ProcessesPlugin,
    PsProcessDiscovery,
    _args_disable_remote_debug,
    _enrich_python_process,
    _probe_python_version_hint,
    _remote_debug_disabled,
    _should_probe_python_version,
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


def test_parse_ps_output_skips_bad_rows_and_recovers_from_bad_quoting() -> None:
    out = parse_ps_output(
        "\n"
        "not-a-pid python python -m app\n"
        "  321 python3.14 python3.14 -c 'unterminated\n"
        "  322 launchd\n"
    )

    assert [proc.pid for proc in out] == [321, 322]
    assert out[0].command == "python3.14"
    assert out[0].is_python is True
    assert out[1].command == "launchd"
    assert out[1].args == "launchd"


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


@pytest.mark.parametrize(
    ("returncode", "stdout"),
    [
        (1, "3.14\n"),
        (0, ""),
        (0, "not-a-version\n"),
    ],
)
def test_probe_python_version_hint_rejects_unusable_probe_output(
    monkeypatch: pytest.MonkeyPatch,
    returncode: int,
    stdout: str,
) -> None:
    class FakeCompleted:
        def __init__(self) -> None:
            self.returncode = returncode
            self.stdout = stdout

    monkeypatch.setattr(Path, "exists", lambda _path: True)
    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kwargs: FakeCompleted())

    assert _probe_python_version_hint(123) is None


def test_probe_python_version_hint_handles_missing_exe_and_os_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "exists", lambda _path: False)
    assert _probe_python_version_hint(123) is None

    monkeypatch.setattr(Path, "exists", lambda _path: True)
    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError))

    assert _probe_python_version_hint(123) is None


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


def test_enrich_python_process_treats_empty_remote_debug_env_as_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_read_bytes(path: Path) -> bytes:
        assert str(path) == "/proc/123/environ"
        return b"PYTHON_DISABLE_REMOTE_DEBUG=\0"

    monkeypatch.setattr(Path, "read_bytes", fake_read_bytes)

    proc = ProcessInfo(
        pid=123,
        command="python3.14",
        args="python3.14 -m service",
        is_python=True,
        python_version_hint="3.14",
    )
    enriched = _enrich_python_process(proc)

    assert enriched.remote_debug_disabled is True


def test_enrich_python_process_leaves_non_python_processes_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        subprocess, "run", lambda *_args, **_kwargs: pytest.fail("should not probe")
    )
    monkeypatch.setattr(Path, "read_bytes", lambda _path: pytest.fail("should not read env"))

    proc = ProcessInfo(pid=123, command="bash", args="bash -lc true", is_python=False)

    assert _enrich_python_process(proc) is proc


def test_enrich_python_process_does_not_execute_python_named_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_exists(path: Path) -> bool:
        return str(path) == "/proc/124/exe"

    def fake_read_bytes(_path: Path) -> bytes:
        raise OSError

    def fake_run(_cmd: list[str], **_kwargs: Any) -> object:
        raise AssertionError("should not execute python-worker")

    monkeypatch.setattr(Path, "exists", fake_exists)
    monkeypatch.setattr(Path, "read_bytes", fake_read_bytes)
    monkeypatch.setattr(subprocess, "run", fake_run)

    proc = ProcessInfo(
        pid=124,
        command="python-worker",
        args="/usr/local/bin/python-worker --serve",
        is_python=True,
    )
    enriched = _enrich_python_process(proc)

    assert enriched.python_version_hint is None


def test_should_probe_python_version_accepts_interpreter_names() -> None:
    assert _should_probe_python_version(
        ProcessInfo(pid=1, command="python", args="/venv/bin/python -m app", is_python=True)
    )
    assert _should_probe_python_version(
        ProcessInfo(pid=2, command="python3", args="python3 -m app", is_python=True)
    )
    assert not _should_probe_python_version(
        ProcessInfo(
            pid=3,
            command="python-worker",
            args="/usr/local/bin/python-worker --serve",
            is_python=True,
        )
    )


def test_args_disable_remote_debug_detects_python_x_option() -> None:
    assert _args_disable_remote_debug("python -X disable_remote_debug -m service") is True
    assert _args_disable_remote_debug("python -Xdisable_remote_debug -m service") is True
    assert _args_disable_remote_debug("python -m service") is False


def test_args_disable_remote_debug_handles_bad_quoting_and_dash_variant() -> None:
    assert _args_disable_remote_debug("python -X disable-remote-debug 'unterminated") is True


def test_remote_debug_disabled_prefers_args_and_tolerates_missing_proc_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "read_bytes", lambda _path: pytest.fail("args should short-circuit"))
    assert _remote_debug_disabled(123, "python -Xdisable-remote-debug -m app") is True

    monkeypatch.setattr(Path, "read_bytes", lambda _path: (_ for _ in ()).throw(OSError))
    assert _remote_debug_disabled(123, "python -m app") is False


def test_ps_process_discovery_filters_self_and_enriches_python(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeCompleted:
        returncode = 0
        stdout = "  111 python3.14 python3.14 -m svc\n  222 bash bash\n"

    monkeypatch.setattr(os, "getpid", lambda: 222)
    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kwargs: FakeCompleted())
    monkeypatch.setattr(Path, "read_bytes", lambda _path: b"PYTHON_DISABLE_REMOTE_DEBUG=1\0")

    processes = PsProcessDiscovery().list_processes()

    assert [(proc.pid, proc.command, proc.remote_debug_disabled) for proc in processes] == [
        (111, "python3.14", True)
    ]


def test_ps_process_discovery_returns_empty_on_ps_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeCompleted:
        returncode = 1
        stdout = ""

    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kwargs: FakeCompleted())

    assert PsProcessDiscovery().list_processes() == []


def test_processes_plugin_preserves_existing_discovery_and_opens_attach_picker() -> None:
    class ExistingDiscovery(ProcessDiscovery):
        def list_processes(self) -> list[ProcessInfo]:
            return []

    host = RecordingHost()
    ctx = make_context(host=host)
    existing = ExistingDiscovery()
    ctx.services.register(PROCESS_DISCOVERY, existing)

    ProcessesPlugin().register(ctx)
    asyncio.run(ctx.commands.get("session.attach").run())

    assert ctx.services.get(PROCESS_DISCOVERY) is existing
    assert isinstance(host.screens[-1], AttachPicker)
