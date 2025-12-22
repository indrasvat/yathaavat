from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from yathaavat.core.services import ServiceKey


class SessionState(StrEnum):
    DISCONNECTED = "DISCONNECTED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"


@dataclass(frozen=True, slots=True)
class ThreadInfo:
    id: int
    name: str


@dataclass(frozen=True, slots=True)
class FrameInfo:
    id: int
    name: str
    path: str | None
    line: int | None


@dataclass(frozen=True, slots=True)
class VariableInfo:
    name: str
    value: str
    type: str | None = None
    variables_reference: int = 0


@dataclass(frozen=True, slots=True)
class BreakpointInfo:
    path: str
    line: int
    verified: bool | None = None
    message: str | None = None


@dataclass(frozen=True, slots=True)
class WatchInfo:
    expression: str
    value: str = ""
    error: str | None = None
    changed: bool = False


@dataclass(frozen=True, slots=True)
class SessionSnapshot:
    state: SessionState = SessionState.DISCONNECTED
    backend: str = ""
    pid: int | None = None
    python: str | None = None
    threads: tuple[ThreadInfo, ...] = ()
    selected_thread_id: int | None = None
    frames: tuple[FrameInfo, ...] = ()
    selected_frame_id: int | None = None
    source_path: str | None = None
    source_line: int | None = None
    source_col: int | None = None
    locals: tuple[VariableInfo, ...] = ()
    watches: tuple[WatchInfo, ...] = ()
    breakpoints: tuple[BreakpointInfo, ...] = ()
    transcript: tuple[str, ...] = ()


SessionListener = Callable[[SessionSnapshot], None]


class SessionStore:
    def __init__(self) -> None:
        self._snapshot = SessionSnapshot()
        self._listeners: list[SessionListener] = []

    def snapshot(self) -> SessionSnapshot:
        return self._snapshot

    def subscribe(
        self, listener: SessionListener, *, emit_current: bool = True
    ) -> Callable[[], None]:
        self._listeners.append(listener)
        if emit_current:
            listener(self._snapshot)

        def unsubscribe() -> None:
            try:
                self._listeners.remove(listener)
            except ValueError:
                return

        return unsubscribe

    def update(self, **changes: Any) -> None:
        self._snapshot = replace(self._snapshot, **changes)
        for listener in tuple(self._listeners):
            listener(self._snapshot)

    def append_transcript(self, line: str, *, max_lines: int = 400) -> None:
        current = self._snapshot.transcript
        next_lines = (*current, line)
        if len(next_lines) > max_lines:
            next_lines = next_lines[-max_lines:]
        self.update(transcript=next_lines)


@runtime_checkable
class SessionManager(Protocol):
    async def connect(self, host: str, port: int) -> None: ...

    async def attach(self, pid: int) -> None: ...

    async def launch(self, target_argv: list[str]) -> None: ...

    async def disconnect(self) -> None: ...

    async def terminate(self) -> None: ...

    async def shutdown(self) -> None: ...

    async def resume(self) -> None: ...

    async def pause(self) -> None: ...

    async def step_over(self) -> None: ...

    async def step_in(self) -> None: ...

    async def select_frame(self, frame_id: int) -> None: ...

    async def evaluate(self, expression: str) -> str: ...

    async def toggle_breakpoint(self, path: str, line: int) -> None: ...


@runtime_checkable
class SafeAttachManager(SessionManager, Protocol):
    async def safe_attach(self, pid: int) -> None: ...


@runtime_checkable
class VariablesManager(SessionManager, Protocol):
    async def get_variables(self, variables_reference: int) -> tuple[VariableInfo, ...]: ...


@runtime_checkable
class RunToCursorManager(SessionManager, Protocol):
    async def run_to_cursor(self, path: str, line: int) -> None: ...


@runtime_checkable
class SilentEvaluateManager(SessionManager, Protocol):
    async def evaluate_silent(self, expression: str) -> str: ...


SESSION_STORE: ServiceKey[SessionStore] = ServiceKey("session.store")
SESSION_MANAGER: ServiceKey[SessionManager] = ServiceKey("session.manager")
