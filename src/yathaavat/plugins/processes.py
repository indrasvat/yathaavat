from __future__ import annotations

import os
import re
import shlex
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from typing import override

from yathaavat.app.attach import AttachPicker
from yathaavat.core import (
    AppContext,
    Command,
    CommandSpec,
    Plugin,
    ProcessInfo,
)
from yathaavat.core.processes import PROCESS_DISCOVERY, ProcessDiscovery
from yathaavat.core.services import ServiceRegistrationError

_PYTHON_LIKE_RE = re.compile(r"\bpython(?:@?\d+(?:\.\d+)*)?\b", re.IGNORECASE)
_PYTHON_VERSION_RE = re.compile(r"python(?:@)?(?P<major>\d)(?:\.(?P<minor>\d+))?", re.IGNORECASE)
_VERSION_OUTPUT_RE = re.compile(r"^(?P<major>\d+)\.(?P<minor>\d+)$")


def parse_ps_output(text: str) -> list[ProcessInfo]:
    processes: list[ProcessInfo] = []
    for line in text.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) < 2:
            continue
        pid_s, comm = parts[0], parts[1]
        try:
            pid = int(pid_s)
        except ValueError:
            continue
        args = parts[2] if len(parts) >= 3 else comm
        argv0 = _argv0(args=args, fallback=comm)
        command = Path(argv0).name or comm
        is_python = _is_python(argv0=argv0, comm=comm)
        processes.append(
            ProcessInfo(
                pid=pid,
                command=command,
                args=args,
                is_python=is_python,
                python_version_hint=_python_version_hint(argv0=argv0, comm=comm)
                if is_python
                else None,
            )
        )
    return processes


def _argv0(*, args: str, fallback: str) -> str:
    stripped = args.strip()
    if not stripped:
        return fallback
    try:
        tokens = shlex.split(stripped, posix=True)
    except ValueError:
        tokens = stripped.split()
    return tokens[0] if tokens else fallback


def _is_python(*, argv0: str, comm: str) -> bool:
    argv0_name = Path(argv0).name
    return (
        _PYTHON_LIKE_RE.search(argv0_name) is not None or _PYTHON_LIKE_RE.search(comm) is not None
    )


def _python_version_hint(*, argv0: str, comm: str) -> str | None:
    match = _PYTHON_VERSION_RE.search(argv0) or _PYTHON_VERSION_RE.search(comm)
    if match:
        major = match.group("major")
        minor = match.group("minor")
        return f"{major}.{minor}" if minor else major
    return None


@dataclass(frozen=True, slots=True)
class PsProcessDiscovery(ProcessDiscovery):
    def list_processes(self) -> list[ProcessInfo]:
        completed = subprocess.run(
            ["ps", "-ww", "-eo", "pid=,comm=,args="],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            return []
        processes = parse_ps_output(completed.stdout)
        own_pid = os.getpid()
        return [_enrich_python_process(p) for p in processes if p.pid != own_pid]


def _enrich_python_process(proc: ProcessInfo) -> ProcessInfo:
    if not proc.is_python:
        return proc

    version = proc.python_version_hint or _probe_python_version_hint(proc.pid)
    remote_debug_disabled = _remote_debug_disabled(proc.pid, proc.args)
    if version == proc.python_version_hint and remote_debug_disabled == proc.remote_debug_disabled:
        return proc
    return replace(
        proc,
        python_version_hint=version,
        remote_debug_disabled=remote_debug_disabled,
    )


def _probe_python_version_hint(pid: int) -> str | None:
    """Probe a live Python process' interpreter version via /proc/<pid>/exe.

    Many real services appear as plain `python` or a venv shim in `ps`, which hides the
    minor version needed to choose Python 3.14's safe attach path. Running the target
    executable in isolated, no-site mode is cheap and avoids importing application code.
    """

    exe = Path(f"/proc/{pid}/exe")
    if not exe.exists():
        return None
    try:
        completed = subprocess.run(
            [
                str(exe),
                "-I",
                "-S",
                "-c",
                "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=1.5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    value = (completed.stdout or "").strip().splitlines()[:1]
    if not value:
        return None
    match = _VERSION_OUTPUT_RE.fullmatch(value[0].strip())
    if match is None:
        return None
    return f"{match.group('major')}.{match.group('minor')}"


def _remote_debug_disabled(pid: int, args: str) -> bool:
    if _args_disable_remote_debug(args):
        return True

    environ = Path(f"/proc/{pid}/environ")
    try:
        data = environ.read_bytes()
    except OSError:
        return False
    for item in data.split(b"\0"):
        if not item.startswith(b"PYTHON_DISABLE_REMOTE_DEBUG="):
            continue
        _name, _sep, value = item.partition(b"=")
        return bool(value)
    return False


def _args_disable_remote_debug(args: str) -> bool:
    try:
        tokens = shlex.split(args, posix=True)
    except ValueError:
        tokens = args.split()
    for idx, token in enumerate(tokens):
        if token in {"-Xdisable_remote_debug", "-Xdisable-remote-debug"}:
            return True
        if token == "-X" and idx + 1 < len(tokens):
            if tokens[idx + 1] in {"disable_remote_debug", "disable-remote-debug"}:
                return True
    return False


@dataclass(frozen=True, slots=True)
class ProcessesPlugin(Plugin):
    @property
    @override
    def id(self) -> str:
        return "processes"

    @override
    def register(self, ctx: AppContext) -> None:
        try:
            ctx.services.register(PROCESS_DISCOVERY, PsProcessDiscovery())
        except ServiceRegistrationError:
            pass

        ctx.commands.register(
            Command(
                CommandSpec(
                    id="session.attach",
                    title="Attach to Process…",
                    summary="Discover local processes and attach (prototype).",
                    default_keys=("ctrl+a",),
                ),
                handler=lambda: ctx.host.push_screen(AttachPicker(ctx=ctx)),
            )
        )


def plugin() -> Plugin:
    return ProcessesPlugin()
