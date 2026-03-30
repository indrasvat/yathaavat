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


class BreakMode(StrEnum):
    NEVER = "never"
    ALWAYS = "always"
    UNHANDLED = "unhandled"
    USER_UNHANDLED = "userUnhandled"


class ExceptionRelation(StrEnum):
    ROOT = "root"
    CAUSE = "cause"
    CONTEXT = "context"
    GROUP_MEMBER = "member"


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
    condition: str | None = None
    hit_condition: str | None = None
    log_message: str | None = None
    verified: bool | None = None
    message: str | None = None


@dataclass(frozen=True, slots=True)
class WatchInfo:
    expression: str
    value: str = ""
    error: str | None = None
    changed: bool = False


@dataclass(frozen=True, slots=True)
class TracebackFrame:
    path: str | None
    line: int | None
    name: str
    text: str | None = None


@dataclass(frozen=True, slots=True)
class ExceptionNode:
    type_name: str
    message: str
    frames: tuple[TracebackFrame, ...] = ()
    children: tuple[ExceptionNode, ...] = ()
    relation: ExceptionRelation = ExceptionRelation.ROOT
    is_group: bool = False


@dataclass(frozen=True, slots=True)
class ExceptionInfo:
    exception_id: str
    break_mode: BreakMode
    stack_trace: str
    tree: ExceptionNode


@dataclass(frozen=True, slots=True)
class CompletionItem:
    label: str
    insert_text: str
    replace_start: int
    replace_length: int
    type: str | None = None


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
    stop_reason: str | None = None
    stop_description: str | None = None
    exception_info: ExceptionInfo | None = None
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

    async def step_out(self) -> None: ...

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


@runtime_checkable
class ThreadSelectionManager(SessionManager, Protocol):
    async def select_thread(self, thread_id: int) -> None: ...


@runtime_checkable
class BreakpointConfigManager(SessionManager, Protocol):
    async def set_breakpoint_config(
        self,
        path: str,
        line: int,
        *,
        condition: str | None = None,
        hit_condition: str | None = None,
        log_message: str | None = None,
    ) -> None: ...


@runtime_checkable
class ExceptionInfoManager(SessionManager, Protocol):
    async def get_exception_info(self, thread_id: int) -> ExceptionInfo | None: ...


@runtime_checkable
class CompletionsManager(SessionManager, Protocol):
    async def complete(self, text: str, *, cursor: int) -> tuple[CompletionItem, ...]: ...


SESSION_STORE: ServiceKey[SessionStore] = ServiceKey("session.store")
SESSION_MANAGER: ServiceKey[SessionManager] = ServiceKey("session.manager")
