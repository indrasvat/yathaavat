from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from yathaavat.core.services import ServiceKey


@dataclass(frozen=True, slots=True)
class ProcessInfo:
    pid: int
    command: str
    args: str
    is_python: bool
    python_version_hint: str | None = None


@runtime_checkable
class ProcessDiscovery(Protocol):
    def list_processes(self) -> list[ProcessInfo]: ...


PROCESS_DISCOVERY: ServiceKey[ProcessDiscovery] = ServiceKey("process.discovery")
