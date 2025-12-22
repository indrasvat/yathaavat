from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from textual import on
from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import ListItem, ListView, Static

from yathaavat.core import (
    SESSION_MANAGER,
    SESSION_STORE,
    AppContext,
    SessionManager,
    SessionSnapshot,
    SessionStore,
    ThreadInfo,
    ThreadSelectionManager,
)


def _get_store(ctx: AppContext) -> SessionStore:
    return ctx.services.get(SESSION_STORE)


def _get_manager(ctx: AppContext) -> SessionManager | None:
    try:
        return ctx.services.get(SESSION_MANAGER)
    except KeyError:
        return None


@dataclass(frozen=True, slots=True)
class _ThreadRow:
    id: int
    label: str


def _thread_rows(threads: tuple[ThreadInfo, ...]) -> list[_ThreadRow]:
    rows: list[_ThreadRow] = []
    for t in threads:
        label = t.name
        if not label:
            label = f"Thread {t.id}"
        rows.append(_ThreadRow(id=t.id, label=label))
    return rows


class ThreadsPanel(Container):
    def __init__(self, *, ctx: AppContext) -> None:
        super().__init__()
        self._ctx = ctx
        self._store = _get_store(ctx)
        self._tasks: set[asyncio.Task[None]] = set()
        self._unsubscribe: Callable[[], None] | None = None

    def compose(self) -> ComposeResult:
        yield ListView(id="threads_list")

    def on_mount(self) -> None:
        self._unsubscribe = self._store.subscribe(self._on_snapshot)

    def on_unmount(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()

    @on(ListView.Selected, "#threads_list")
    def _on_selected(self, event: ListView.Selected) -> None:
        item = event.item
        thread_id = getattr(item, "thread_id", None)
        if not isinstance(thread_id, int):
            return

        manager = _get_manager(self._ctx)
        if manager is None:
            return
        if not isinstance(manager, ThreadSelectionManager):
            self._ctx.host.notify("Thread selection is not supported by this backend.", timeout=2.5)
            return

        async def _select() -> None:
            try:
                await manager.select_thread(thread_id)
            except Exception as exc:
                self._ctx.host.notify(str(exc), timeout=2.5)

        task = asyncio.create_task(_select())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _on_snapshot(self, snapshot: SessionSnapshot) -> None:
        lv = self.query_one("#threads_list", ListView)
        rows = _thread_rows(snapshot.threads)
        lv.clear()
        for row in rows:
            li = ListItem(Static(f"{row.label}  [{row.id}]"))
            li.thread_id = row.id  # type: ignore[attr-defined]
            lv.append(li)
        if snapshot.selected_thread_id is not None:
            for i, row in enumerate(rows):
                if row.id == snapshot.selected_thread_id:
                    lv.index = i
                    break
