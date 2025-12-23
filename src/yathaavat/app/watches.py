from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import ClassVar

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import DataTable, Static

from yathaavat.app.expression import ExpressionInput
from yathaavat.core import (
    SESSION_MANAGER,
    SESSION_STORE,
    AppContext,
    SessionSnapshot,
    SessionState,
    SessionStore,
    SilentEvaluateManager,
    WatchInfo,
)


def _get_store(ctx: AppContext) -> SessionStore:
    return ctx.services.get(SESSION_STORE)


def _get_manager(ctx: AppContext) -> SilentEvaluateManager | None:
    try:
        manager = ctx.services.get(SESSION_MANAGER)
    except KeyError:
        return None
    return manager if isinstance(manager, SilentEvaluateManager) else None


class AddWatchDialog(ModalScreen[None]):
    BINDINGS: ClassVar[list[BindingType]] = [("escape", "app.pop_screen", "Close")]

    def __init__(self, *, ctx: AppContext) -> None:
        super().__init__()
        self._ctx = ctx

    def compose(self) -> ComposeResult:
        yield Container(
            Horizontal(
                Static("Watch", id="watch_title"),
                ExpressionInput(
                    ctx=self._ctx, placeholder="expression (e.g. order.total)", id="watch_input"
                ),
                Static("", id="watch_status"),
                id="watch_row",
            ),
            Static("Enter add  •  Esc close", id="watch_hint"),
            id="watch_root",
        )

    def on_mount(self) -> None:
        self.styles.background = "transparent"
        self.query_one(ExpressionInput).focus_input()

    @on(ExpressionInput.Submitted, "#watch_input")
    def _on_submit(self, event: ExpressionInput.Submitted) -> None:
        expr = event.text.strip()
        if not expr:
            return

        store = _get_store(self._ctx)
        snap = store.snapshot()
        existing = {w.expression for w in snap.watches}
        if expr in existing:
            self.query_one("#watch_status", Static).update("exists")
            return

        store.update(watches=(*snap.watches, WatchInfo(expression=expr)))
        control = event.control
        if isinstance(control, ExpressionInput):
            control.clear()
        self.query_one("#watch_status", Static).update("added")


class WatchesTable(DataTable[str | Text]):
    BINDINGS: ClassVar[list[BindingType]] = [
        ("d", "delete_watch", "Delete"),
        ("y", "copy_value", "Copy Value"),
    ]

    def __init__(self, *, ctx: AppContext, store: SessionStore) -> None:
        super().__init__(
            id="watches_table",
            cursor_type="row",
            zebra_stripes=True,
            show_row_labels=False,
            cell_padding=0,
        )
        self._ctx = ctx
        self._store = store
        self._rows: list[WatchInfo] = []
        self.add_columns("Expr", "Value")

    def set_watches(self, watches: tuple[WatchInfo, ...]) -> None:
        self.clear(columns=False)
        self._rows = list(watches)
        if not self._rows:
            self.add_row("No watches.  Ctrl+W to add.", "")
            return

        for w in self._rows:
            value_cell: str | Text
            if w.error:
                value_cell = Text(w.error, style="bold #ff6b6b")
            else:
                value_cell = w.value
                if w.changed:
                    value_cell = Text(f"Δ {w.value}", style="bold #7cfc9a")
            self.add_row(w.expression, value_cell)

    async def action_delete_watch(self) -> None:
        watch = self._selected()
        if watch is None:
            return
        snap = self._store.snapshot()
        updated = tuple(w for w in snap.watches if w.expression != watch.expression)
        self._store.update(watches=updated)
        self._ctx.host.notify("Deleted watch.", timeout=1.2)

    def action_copy_value(self) -> None:
        watch = self._selected()
        if watch is None:
            return
        payload = watch.error or watch.value
        self.app.copy_to_clipboard(payload)
        self._ctx.host.notify("Copied value.", timeout=1.2)

    def _selected(self) -> WatchInfo | None:
        row = self.cursor_row
        if row is None or row < 0 or row >= len(self._rows):
            return None
        return self._rows[row]


@dataclass(frozen=True, slots=True)
class _EvalKey:
    frame_id: int | None
    exec_path: str | None
    exec_line: int | None
    expressions: tuple[str, ...]


class WatchesPanel(Container):
    def __init__(self, *, ctx: AppContext) -> None:
        super().__init__()
        self._ctx = ctx
        self._store = _get_store(ctx)
        self._unsubscribe: Callable[[], None] | None = None
        self._table = WatchesTable(ctx=ctx, store=self._store)
        self._last: tuple[WatchInfo, ...] = ()
        self._eval_key: _EvalKey | None = None
        self._eval_task: asyncio.Task[None] | None = None

    def compose(self) -> ComposeResult:
        yield self._table

    def on_mount(self) -> None:
        self._unsubscribe = self._store.subscribe(self._on_snapshot)

    def on_unmount(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
        if self._eval_task is not None:
            self._eval_task.cancel()

    def _on_snapshot(self, snapshot: SessionSnapshot) -> None:
        if snapshot.watches != self._last:
            self._last = snapshot.watches
            self._table.set_watches(snapshot.watches)

        key = self._compute_eval_key(snapshot)
        if key is None:
            self._eval_key = None
            if self._eval_task is not None:
                self._eval_task.cancel()
                self._eval_task = None
            return

        if key == self._eval_key:
            return
        self._eval_key = key

        if self._eval_task is not None:
            self._eval_task.cancel()
        self._eval_task = asyncio.create_task(self._eval_watches(key))

    def _compute_eval_key(self, snapshot: SessionSnapshot) -> _EvalKey | None:
        if snapshot.state != SessionState.PAUSED:
            return None
        if not snapshot.watches:
            return None
        if _get_manager(self._ctx) is None:
            return None

        frame_id = snapshot.selected_frame_id or (
            snapshot.frames[0].id if snapshot.frames else None
        )
        frame = next((f for f in snapshot.frames if f.id == frame_id), None)
        exec_path = frame.path if frame is not None else None
        exec_line = frame.line if frame is not None else None
        expressions = tuple(w.expression for w in snapshot.watches)
        return _EvalKey(
            frame_id=frame_id,
            exec_path=exec_path if isinstance(exec_path, str) else None,
            exec_line=exec_line if isinstance(exec_line, int) else None,
            expressions=expressions,
        )

    async def _eval_watches(self, key: _EvalKey) -> None:
        manager = _get_manager(self._ctx)
        if manager is None:
            return

        snap = self._store.snapshot()
        watches = snap.watches
        results: dict[str, tuple[str, str | None]] = {}
        for w in watches:
            if w.expression not in key.expressions:
                continue
            try:
                results[w.expression] = (await manager.evaluate_silent(w.expression), None)
            except Exception as exc:
                results[w.expression] = ("", str(exc))

        # Avoid applying stale results if the session has moved on.
        if self._compute_eval_key(self._store.snapshot()) != key:
            return

        current = self._store.snapshot().watches
        updated: list[WatchInfo] = []
        for w in current:
            if w.expression not in results:
                continue
            value, error = results[w.expression]
            if error is not None:
                updated.append(WatchInfo(expression=w.expression, value=w.value, error=error))
                continue
            changed = bool(w.value) and w.value != value
            updated.append(WatchInfo(expression=w.expression, value=value, changed=changed))

        self._store.update(watches=tuple(updated))
