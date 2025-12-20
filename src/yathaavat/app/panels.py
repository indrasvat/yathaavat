from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from textual import on
from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Input, ListItem, ListView, Static

from yathaavat.core import (
    SESSION_MANAGER,
    SESSION_STORE,
    AppContext,
    BreakpointInfo,
    FrameInfo,
    SessionManager,
    SessionSnapshot,
    SessionStore,
    VariableInfo,
)


def _get_store(ctx: AppContext) -> SessionStore:
    return ctx.services.get(SESSION_STORE)


def _get_manager(ctx: AppContext) -> SessionManager | None:
    try:
        return ctx.services.get(SESSION_MANAGER)
    except KeyError:
        return None


class TranscriptPanel(Static):
    def __init__(self, *, ctx: AppContext) -> None:
        super().__init__("", expand=True)
        self._store = _get_store(ctx)
        self._unsubscribe: Callable[[], None] | None = None

    def on_mount(self) -> None:
        self._unsubscribe = self._store.subscribe(self._on_snapshot)

    def on_unmount(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()

    def _on_snapshot(self, snapshot: SessionSnapshot) -> None:
        text = "\n".join(snapshot.transcript[-250:]) or "—"
        self.update(text)


@dataclass(frozen=True, slots=True)
class _FrameRow:
    id: int
    label: str


class StackPanel(Container):
    def __init__(self, *, ctx: AppContext) -> None:
        super().__init__()
        self._ctx = ctx
        self._store = _get_store(ctx)
        self._tasks: set[asyncio.Task[None]] = set()
        self._unsubscribe: Callable[[], None] | None = None

    def compose(self) -> ComposeResult:
        yield ListView(id="stack_list")

    def on_mount(self) -> None:
        self._unsubscribe = self._store.subscribe(self._on_snapshot)

    def on_unmount(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()

    @on(ListView.Selected, "#stack_list")
    def _on_selected(self, event: ListView.Selected) -> None:
        item = event.item
        frame_id = getattr(item, "frame_id", None)
        if not isinstance(frame_id, int):
            return
        manager = _get_manager(self._ctx)
        if manager is None:
            return

        async def _select() -> None:
            try:
                await manager.select_frame(frame_id)
            except Exception as exc:
                self._ctx.host.notify(str(exc), timeout=2.5)

        task = asyncio.create_task(_select())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _on_snapshot(self, snapshot: SessionSnapshot) -> None:
        lv = self.query_one("#stack_list", ListView)
        rows = _frame_rows(snapshot.frames)
        lv.clear()
        for row in rows:
            li = ListItem(Static(row.label))
            li.frame_id = row.id  # type: ignore[attr-defined]
            lv.append(li)
        if snapshot.selected_frame_id is not None:
            for i, row in enumerate(rows):
                if row.id == snapshot.selected_frame_id:
                    lv.index = i
                    break


def _frame_rows(frames: tuple[FrameInfo, ...]) -> list[_FrameRow]:
    rows: list[_FrameRow] = []
    for frame in frames:
        loc = ""
        if frame.path and frame.line:
            loc = f"  {Path(frame.path).name}:{frame.line}"
        rows.append(_FrameRow(id=frame.id, label=f"{frame.name}{loc}"))
    return rows


class SourcePanel(Static):
    def __init__(self, *, ctx: AppContext) -> None:
        super().__init__("", expand=True)
        self._store = _get_store(ctx)
        self._unsubscribe: Callable[[], None] | None = None

    def on_mount(self) -> None:
        self._unsubscribe = self._store.subscribe(self._on_snapshot)

    def on_unmount(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()

    def _on_snapshot(self, snapshot: SessionSnapshot) -> None:
        frame = _selected_frame(snapshot)
        self.update(_render_source(frame, snapshot.breakpoints))


def _selected_frame(snapshot: SessionSnapshot) -> FrameInfo | None:
    if snapshot.selected_frame_id is None:
        return snapshot.frames[0] if snapshot.frames else None
    for frame in snapshot.frames:
        if frame.id == snapshot.selected_frame_id:
            return frame
    return snapshot.frames[0] if snapshot.frames else None


def _render_source(frame: FrameInfo | None, breakpoints: tuple[BreakpointInfo, ...]) -> str:
    if frame is None:
        return "No frame selected."
    if frame.path is None or frame.line is None:
        return f"{frame.name}\n\n(no source information)"

    path = str(Path(frame.path).expanduser().resolve())
    p = Path(path)
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return f"{frame.path}:{frame.line}\n\n(unreadable source)"

    line_no = frame.line
    bp_lines = {bp.line for bp in breakpoints if bp.path == path}
    start = max(1, line_no - 6)
    end = min(len(lines), line_no + 6)
    width = len(str(end))
    out = [f"{path}:{frame.line}", ""]
    for i in range(start, end + 1):
        prefix = "->" if i == line_no else "  "
        marker = "●" if i in bp_lines else " "
        out.append(f"{marker}{prefix} {i:>{width}}  {lines[i - 1]}")
    return "\n".join(out)


class LocalsPanel(Static):
    def __init__(self, *, ctx: AppContext) -> None:
        super().__init__("", expand=True)
        self._store = _get_store(ctx)
        self._unsubscribe: Callable[[], None] | None = None

    def on_mount(self) -> None:
        self._unsubscribe = self._store.subscribe(self._on_snapshot)

    def on_unmount(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()

    def _on_snapshot(self, snapshot: SessionSnapshot) -> None:
        if not snapshot.locals:
            self.update("No locals.")
            return
        self.update(_render_locals(snapshot.locals))


def _render_locals(vars: tuple[VariableInfo, ...]) -> str:
    width = max((len(v.name) for v in vars), default=5)
    out = []
    for v in vars[:250]:
        t = f": {v.type}" if v.type else ""
        out.append(f"{v.name:<{width}}{t} = {v.value}")
    return "\n".join(out)


class ConsolePanel(Container):
    def __init__(self, *, ctx: AppContext) -> None:
        super().__init__()
        self._ctx = ctx
        self._lines: list[str] = []
        self._tasks: set[asyncio.Task[None]] = set()

    def compose(self) -> ComposeResult:
        yield Static("", id="console_log", expand=True)
        yield Input(placeholder=">>>", id="console_input")

    @on(Input.Submitted, "#console_input")
    def _on_submit(self, event: Input.Submitted) -> None:
        expr = event.value.strip()
        event.input.value = ""
        if not expr:
            return
        manager = _get_manager(self._ctx)
        if manager is None:
            self._append(f">>> {expr}\n(no session)")
            return

        async def _eval() -> None:
            try:
                result = await manager.evaluate(expr)
            except Exception as exc:
                self._append(f">>> {expr}\nerror: {exc}")
                return
            self._append(f">>> {expr}\n{result}")

        task = asyncio.create_task(_eval())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _append(self, text: str) -> None:
        self._lines.extend(text.splitlines())
        self._lines = self._lines[-200:]
        self.query_one("#console_log", Static).update("\n".join(self._lines))
