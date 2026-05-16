from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from textual.app import App, ComposeResult
from textual.screen import Screen
from textual.widget import Widget

from yathaavat.core import (
    SESSION_MANAGER,
    SESSION_STORE,
    AppContext,
    CommandRegistry,
    CompletionItem,
    SessionStore,
    TaskGraphInfo,
    VariableInfo,
    WidgetRegistry,
)
from yathaavat.core.services import ServiceRegistry


@dataclass(slots=True)
class RecordingHost:
    notifications: list[tuple[str, float]] = field(default_factory=list)
    screens: list[Screen[Any]] = field(default_factory=list)
    exited: bool = False
    zooms: int = 0
    source_find_opens: int = 0
    popped: int = 0

    def notify(self, message: str, *, timeout: float = 1.2) -> None:
        self.notifications.append((message, timeout))

    def exit(self) -> None:
        self.exited = True

    def toggle_zoom(self) -> None:
        self.zooms += 1

    def open_source_find(self) -> None:
        self.source_find_opens += 1

    def push_screen(self, screen: Screen[Any]) -> None:
        self.screens.append(screen)

    def pop_screen(self) -> None:
        self.popped += 1


@dataclass(slots=True)
class RecordingManager:
    calls: list[tuple[str, tuple[Any, ...]]] = field(default_factory=list)
    evaluate_result: str = "result"
    silent_results: dict[str, str] = field(default_factory=dict)
    variables: dict[int, tuple[VariableInfo, ...]] = field(default_factory=dict)
    completions: tuple[CompletionItem, ...] = ()
    fail: dict[str, Exception] = field(default_factory=dict)
    refreshed_graph: TaskGraphInfo | None = None

    def _record(self, name: str, *args: Any) -> None:
        self.calls.append((name, args))
        exc = self.fail.get(name)
        if exc is not None:
            raise exc

    async def connect(self, host: str, port: int) -> None:
        self._record("connect", host, port)

    async def attach(self, pid: int) -> None:
        self._record("attach", pid)

    async def safe_attach(self, pid: int) -> None:
        self._record("safe_attach", pid)

    async def launch(self, target_argv: list[str]) -> None:
        self._record("launch", tuple(target_argv))

    async def disconnect(self) -> None:
        self._record("disconnect")

    async def terminate(self) -> None:
        self._record("terminate")

    async def shutdown(self) -> None:
        self._record("shutdown")

    async def resume(self) -> None:
        self._record("resume")

    async def pause(self) -> None:
        self._record("pause")

    async def step_over(self) -> None:
        self._record("step_over")

    async def step_in(self) -> None:
        self._record("step_in")

    async def step_out(self) -> None:
        self._record("step_out")

    async def select_frame(self, frame_id: int) -> None:
        self._record("select_frame", frame_id)

    async def select_thread(self, thread_id: int) -> None:
        self._record("select_thread", thread_id)

    async def evaluate(self, expression: str) -> str:
        self._record("evaluate", expression)
        return self.evaluate_result

    async def evaluate_silent(self, expression: str) -> str:
        self._record("evaluate_silent", expression)
        return self.silent_results.get(expression, self.evaluate_result)

    async def toggle_breakpoint(self, path: str, line: int) -> None:
        self._record("toggle_breakpoint", path, line)

    async def set_breakpoint_config(
        self,
        path: str,
        line: int,
        *,
        condition: str | None = None,
        hit_condition: str | None = None,
        log_message: str | None = None,
    ) -> None:
        self._record("set_breakpoint_config", path, line, condition, hit_condition, log_message)

    async def run_to_cursor(self, path: str, line: int) -> None:
        self._record("run_to_cursor", path, line)

    async def get_variables(self, variables_reference: int) -> tuple[VariableInfo, ...]:
        self._record("get_variables", variables_reference)
        return self.variables.get(variables_reference, ())

    async def complete(self, text: str, *, cursor: int) -> tuple[CompletionItem, ...]:
        self._record("complete", text, cursor)
        return self.completions

    async def refresh_tasks(self) -> None:
        self._record("refresh_tasks")

    async def select_task(self, task_id: str) -> None:
        self._record("select_task", task_id)


class SingleWidgetApp(App[None]):
    def __init__(self, widget: Widget | Callable[[], Widget]) -> None:
        super().__init__()
        self._widget_or_factory = widget
        self.widget: Widget | None = None

    def compose(self) -> ComposeResult:
        widget = (
            self._widget_or_factory()
            if callable(self._widget_or_factory)
            else self._widget_or_factory
        )
        self.widget = widget
        yield widget


def make_context(
    *,
    host: RecordingHost | None = None,
    store: SessionStore | None = None,
    manager: object | None = None,
) -> AppContext:
    services = ServiceRegistry()
    session_store = store or SessionStore()
    services.register(SESSION_STORE, session_store)
    if manager is not None:
        services.register(SESSION_MANAGER, manager)
    return AppContext(
        commands=CommandRegistry(),
        widgets=WidgetRegistry(),
        services=services,
        host=host or RecordingHost(),
    )
