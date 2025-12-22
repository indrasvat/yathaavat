from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from rich.style import Style
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container
from textual.events import MouseDown
from textual.strip import Strip
from textual.widgets import DataTable, Input, ListItem, ListView, RichLog, Static, TextArea

from yathaavat.app.breakpoint import BreakpointEditDialog
from yathaavat.app.source_gutter import GutterMarker, apply_gutter_marker, marker_for_breakpoint
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
    VariablesManager,
)


def _get_store(ctx: AppContext) -> SessionStore:
    return ctx.services.get(SESSION_STORE)


def _get_manager(ctx: AppContext) -> SessionManager | None:
    try:
        return ctx.services.get(SESSION_MANAGER)
    except KeyError:
        return None


class TranscriptPanel(Container):
    def __init__(self, *, ctx: AppContext) -> None:
        super().__init__()
        self._store = _get_store(ctx)
        self._unsubscribe: Callable[[], None] | None = None
        self._last_len = 0

    def compose(self) -> ComposeResult:
        yield RichLog(id="transcript_log", max_lines=600, wrap=True, auto_scroll=True)

    def on_mount(self) -> None:
        self._unsubscribe = self._store.subscribe(self._on_snapshot)

    def on_unmount(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()

    def _on_snapshot(self, snapshot: SessionSnapshot) -> None:
        log = self.query_one("#transcript_log", RichLog)
        lines = snapshot.transcript
        if len(lines) < self._last_len:
            log.clear()
            self._last_len = 0
        for line in lines[self._last_len :]:
            log.write(line)
        self._last_len = len(lines)


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


def _language_for_path(path: Path) -> str | None:
    match path.suffix.lower():
        case ".py":
            return "python"
        case ".toml":
            return "toml"
        case ".json":
            return "json"
        case ".yaml" | ".yml":
            return "yaml"
        case ".md":
            return "markdown"
        case _:
            return None


class CodeView(TextArea):
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("up", "cursor_up", show=False),
        Binding("down", "cursor_down", show=False),
        Binding("left", "cursor_left", show=False),
        Binding("right", "cursor_right", show=False),
        Binding("pageup", "cursor_page_up", show=False),
        Binding("pagedown", "cursor_page_down", show=False),
        Binding("home", "cursor_line_start", show=False),
        Binding("end", "cursor_line_end", show=False),
        Binding("ctrl+f", "app.command('source.find')", show=False),
        Binding("ctrl+g", "app.command('source.goto')", show=False),
        Binding("enter", "app.command('debug.run_to_cursor')", show=False),
        Binding("b", "app.command('breakpoint.toggle')", show=False),
        Binding("y", "copy_selection", show=False),
    ]

    def __init__(self) -> None:
        super().__init__(
            "",
            language="python",
            theme="monokai",
            read_only=True,
            soft_wrap=False,
            show_line_numbers=True,
            highlight_cursor_line=True,
            show_cursor=True,
            id="source_view",
        )
        self.path: str | None = None
        self._markers: dict[int, GutterMarker] = {}
        self._exec_path: str | None = None
        self._exec_line: int | None = None

    def line_number_at_viewport_y(self, y: int) -> int | None:
        scroll_x, scroll_y = self.scroll_offset
        _ = scroll_x

        wrapped_document = self.wrapped_document
        absolute_y = int(scroll_y) + y
        if absolute_y < 0 or absolute_y >= wrapped_document.height:
            return None

        try:
            line_info = wrapped_document._offset_to_line_info[absolute_y]
        except IndexError:
            return None
        if line_info is None:
            return None

        line_index, _section_offset = line_info
        return int(line_index) + self.line_number_start

    def action_copy_selection(self) -> None:
        text = self.selected_text
        if not text:
            self.app.notify("Nothing selected.", timeout=1.2)
            return
        self.app.copy_to_clipboard(text)
        self.app.notify("Copied selection.", timeout=1.2)

    def set_breakpoints(self, breakpoints: tuple[BreakpointInfo, ...]) -> None:
        markers = {bp.line: marker_for_breakpoint(bp) for bp in breakpoints}
        if markers == self._markers:
            return
        self._markers = markers
        self.refresh()

    def set_execution_location(self, path: str | None, line: int | None) -> None:
        if path == self._exec_path and line == self._exec_line:
            return
        self._exec_path = path
        self._exec_line = line
        self.refresh()

    def render_line(self, y: int) -> Strip:
        strip = super().render_line(y)
        if not self.show_line_numbers:
            return strip

        show_exec = (
            self._exec_line is not None
            and self._exec_path is not None
            and self.path == self._exec_path
        )
        if not self._markers and not show_exec:
            return strip

        scroll_x, scroll_y = self.scroll_offset
        _ = scroll_x
        absolute_y = int(scroll_y) + y
        wrapped_document = self.wrapped_document
        if absolute_y < 0 or absolute_y >= wrapped_document.height:
            return strip

        try:
            line_info = wrapped_document._offset_to_line_info[absolute_y]
        except IndexError:
            return strip
        if line_info is None:
            return strip
        line_index, section_offset = line_info
        if section_offset != 0:
            return strip

        line_no = int(line_index) + self.line_number_start
        marker = self._markers.get(line_no)
        if marker is not None:
            strip = apply_gutter_marker(strip, gutter_width=self.gutter_width, marker=marker)

        if show_exec and self._exec_line == line_no:
            strip = strip.apply_style(Style(bgcolor="#1a2a40"))

        return strip


class SourcePanel(Container):
    def __init__(self, *, ctx: AppContext) -> None:
        super().__init__()
        self._ctx = ctx
        self._store = _get_store(ctx)
        self._unsubscribe: Callable[[], None] | None = None
        self._path: str | None = None
        self._line: int | None = None
        self._col: int | None = None
        self._syncing_cursor = False
        self._tasks: set[asyncio.Task[None]] = set()

    def compose(self) -> ComposeResult:
        yield Static("", id="source_header")
        yield CodeView()

    def on_mount(self) -> None:
        self._unsubscribe = self._store.subscribe(self._on_snapshot)

    def on_unmount(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()

    @on(TextArea.SelectionChanged, "#source_view")
    def _on_cursor_moved(self, event: TextArea.SelectionChanged) -> None:
        if self._syncing_cursor:
            return
        editor = event.text_area
        if not isinstance(editor, CodeView):
            return
        if editor.path is None:
            return
        row, col = editor.cursor_location
        line = row + editor.line_number_start
        col1 = col + 1
        snap = self._store.snapshot()
        self._line = line
        self._col = col1
        if (
            snap.source_path == editor.path
            and snap.source_line == line
            and (snap.source_col or 1) == col1
        ):
            return
        self._store.update(source_path=editor.path, source_line=line, source_col=col1)

    @on(MouseDown, "#source_view")
    def _on_gutter_click(self, event: MouseDown) -> None:
        if event.button != 1:
            return

        editor = event.widget
        if not isinstance(editor, CodeView):
            return

        offset = event.get_content_offset(editor)
        if offset is None:
            return

        # Only treat clicks in the line-number gutter as breakpoint toggles.
        if int(offset.x) >= editor.gutter_width:
            return

        path = editor.path
        if not isinstance(path, str) or not path:
            return

        line = editor.line_number_at_viewport_y(int(offset.y))
        if line is None:
            return

        # Move the Source cursor to the clicked line (useful for run-to-cursor + local commands).
        self._store.update(source_path=path, source_line=line, source_col=1)

        manager = _get_manager(self._ctx)
        if manager is None:
            self._ctx.host.notify("No session.", timeout=2.0)
            return

        async def _toggle() -> None:
            try:
                await manager.toggle_breakpoint(path, line)
            except Exception as exc:
                self._ctx.host.notify(str(exc), timeout=2.5)

        task = asyncio.create_task(_toggle())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

        event.stop()
        event.prevent_default()

    def _on_snapshot(self, snapshot: SessionSnapshot) -> None:
        header = self.query_one("#source_header", Static)
        editor = self.query_one("#source_view", CodeView)

        self._syncing_cursor = True
        try:
            raw_path = snapshot.source_path
            line = snapshot.source_line
            col = snapshot.source_col
            col = col if isinstance(col, int) and col > 0 else 1

            exec_path: str | None = None
            exec_line: int | None = None
            frame_id = snapshot.selected_frame_id or (
                snapshot.frames[0].id if snapshot.frames else None
            )
            frame = next((f for f in snapshot.frames if f.id == frame_id), None)
            if frame is not None and frame.path and isinstance(frame.line, int):
                try:
                    exec_path = str(Path(frame.path).expanduser().resolve())
                    exec_line = frame.line
                except OSError:
                    exec_path = None
                    exec_line = None
            editor.set_execution_location(exec_path, exec_line)

            if not raw_path or not isinstance(line, int):
                header.update("No frame selected.")
                editor.path = None
                editor.show_line_numbers = False
                editor.text = ""
                editor.set_breakpoints(())
                self._path = None
                self._line = None
                self._col = None
                return

            resolved = str(Path(raw_path).expanduser().resolve())
            if resolved != self._path:
                try:
                    text = Path(resolved).read_text(encoding="utf-8", errors="replace")
                except OSError:
                    header.update(f"{raw_path}:{line}")
                    editor.path = None
                    editor.show_line_numbers = False
                    editor.text = "(unreadable source)"
                    editor.set_breakpoints(())
                    self._path = None
                    self._line = None
                    self._col = None
                    return

                lang = _language_for_path(Path(resolved)) or "text"
                header.update(f"{resolved}:{line}")
                editor.language = lang
                editor.show_line_numbers = True
                editor.text = text
                editor.path = resolved
                self._path = resolved
                self._line = None
                self._col = None

            editor.set_breakpoints(tuple(bp for bp in snapshot.breakpoints if bp.path == resolved))

            header_text = f"{resolved}:{line}"
            if (
                exec_path is not None
                and exec_line is not None
                and (exec_path != resolved or exec_line != line)
            ):
                header_text = f"{header_text}  (exec {Path(exec_path).name}:{exec_line})"
            header.update(header_text)

            if line != self._line or col != self._col:
                row = max(line - 1, 0)
                col0 = max(col - 1, 0)
                try:
                    max_col0 = max(len(editor.document.get_line(row)), 0)
                except Exception:
                    max_col0 = 0
                col0 = min(col0, max_col0)
                self._line = line
                self._col = col
                editor.cursor_location = (row, col0)
                editor.scroll_to(y=max(line - 7, 0), animate=False, immediate=True)
        finally:
            self._syncing_cursor = False


@dataclass(frozen=True, slots=True)
class _VarNode:
    name: str
    value: str
    type: str | None
    variables_reference: int
    depth: int


class LocalsTable(DataTable[str]):
    BINDINGS: ClassVar[list[BindingType]] = [
        ("enter", "toggle_expand", "Expand"),
        ("y", "copy_value", "Copy Value"),
    ]

    def __init__(self, *, ctx: AppContext) -> None:
        super().__init__(
            id="locals_table",
            cursor_type="row",
            zebra_stripes=True,
            show_row_labels=False,
            cell_padding=0,
        )
        self._ctx = ctx
        self._root: tuple[VariableInfo, ...] = ()
        self._expanded: set[int] = set()
        self._cache: dict[int, tuple[VariableInfo, ...]] = {}
        self._flat: list[_VarNode] = []
        self.add_columns("Name", "Type", "Value")

    def set_root(self, locals_: tuple[VariableInfo, ...]) -> None:
        if locals_ == self._root:
            return
        self._root = locals_
        self._expanded.clear()
        self._cache.clear()
        self._rebuild()

    async def action_toggle_expand(self) -> None:
        node = self._selected_node()
        if node is None or node.variables_reference <= 0:
            return

        ref = node.variables_reference
        if ref in self._expanded:
            self._expanded.remove(ref)
            self._rebuild()
            return

        manager = _get_manager(self._ctx)
        if not isinstance(manager, VariablesManager):
            self._ctx.host.notify(
                "Variable expansion is not supported by this session.",
                timeout=2.5,
            )
            return

        if ref not in self._cache:
            try:
                self._ctx.host.notify("Loading variables…", timeout=1.0)
                self._cache[ref] = await manager.get_variables(ref)
            except Exception as exc:
                self._ctx.host.notify(str(exc), timeout=2.5)
                return

        self._expanded.add(ref)
        self._rebuild()

    def action_copy_value(self) -> None:
        node = self._selected_node()
        if node is None:
            return
        self.app.copy_to_clipboard(node.value)
        self._ctx.host.notify("Copied value.", timeout=1.2)

    def _selected_node(self) -> _VarNode | None:
        row = self.cursor_row
        if row is None:
            return None
        if row < 0 or row >= len(self._flat):
            return None
        return self._flat[row]

    def _rebuild(self) -> None:
        self.clear(columns=False)
        self._flat = []
        if not self._root:
            self.add_row("No locals.", "", "")
            return

        def add_vars(vars_: tuple[VariableInfo, ...], *, depth: int) -> None:
            for v in vars_:
                ref = v.variables_reference
                arrow = " "
                if ref > 0:
                    arrow = "▾" if ref in self._expanded else "▸"
                name = f"{'  ' * depth}{arrow} {v.name}"
                vtype = v.type or ""
                self.add_row(name, vtype, v.value)
                self._flat.append(
                    _VarNode(
                        name=v.name,
                        value=v.value,
                        type=v.type,
                        variables_reference=ref,
                        depth=depth,
                    )
                )
                if ref in self._expanded:
                    children = self._cache.get(ref) or ()
                    add_vars(children, depth=depth + 1)

        add_vars(self._root, depth=0)


class LocalsPanel(Container):
    def __init__(self, *, ctx: AppContext) -> None:
        super().__init__()
        self._store = _get_store(ctx)
        self._unsubscribe: Callable[[], None] | None = None
        self._table = LocalsTable(ctx=ctx)

    def compose(self) -> ComposeResult:
        yield self._table

    def on_mount(self) -> None:
        self._unsubscribe = self._store.subscribe(self._on_snapshot)

    def on_unmount(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()

    def _on_snapshot(self, snapshot: SessionSnapshot) -> None:
        self._table.set_root(snapshot.locals)


class BreakpointsTable(DataTable[str]):
    BINDINGS: ClassVar[list[BindingType]] = [
        ("d", "delete_breakpoint", "Delete"),
        ("enter", "jump", "Jump"),
        ("e", "edit_breakpoint", "Edit"),
        ("y", "copy_location", "Copy Location"),
    ]

    def __init__(self, *, ctx: AppContext, store: SessionStore) -> None:
        super().__init__(
            id="breakpoints_table",
            cursor_type="row",
            zebra_stripes=True,
            show_row_labels=False,
            cell_padding=0,
        )
        self._ctx = ctx
        self._store = store
        self._rows: list[BreakpointInfo] = []
        self.add_columns("File", "Line", "✓", "Message")

    def set_breakpoints(self, breakpoints: tuple[BreakpointInfo, ...]) -> None:
        self.clear(columns=False)
        self._rows = list(breakpoints)
        if not self._rows:
            self.add_row("No breakpoints.", "", "", "")
            return
        for bp in self._rows:
            p = Path(bp.path)
            file = p.name if bp.path else "?"
            status = "✓" if bp.verified else ("…" if bp.verified is None else "✗")
            msg = _format_breakpoint_details(bp)
            self.add_row(file, str(bp.line), status, msg)

    @on(DataTable.RowHighlighted)
    def _on_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.cursor_row < 0 or event.cursor_row >= len(self._rows):
            return
        bp = self._rows[event.cursor_row]
        snap = self._store.snapshot()
        if snap.source_path == bp.path and snap.source_line == bp.line:
            return
        self._store.update(source_path=bp.path, source_line=bp.line, source_col=1)

    async def action_delete_breakpoint(self) -> None:
        bp = self._selected()
        if bp is None:
            return
        manager = _get_manager(self._ctx)
        if manager is None:
            self._ctx.host.notify("No session.", timeout=2.0)
            return
        try:
            await manager.toggle_breakpoint(bp.path, bp.line)
        except Exception as exc:
            self._ctx.host.notify(str(exc), timeout=2.5)

    def action_jump(self) -> None:
        bp = self._selected()
        if bp is None:
            return
        self._store.update(source_path=bp.path, source_line=bp.line, source_col=1)

    def action_copy_location(self) -> None:
        bp = self._selected()
        if bp is None:
            return
        self.app.copy_to_clipboard(f"{bp.path}:{bp.line}")
        self._ctx.host.notify("Copied location.", timeout=1.2)

    def action_edit_breakpoint(self) -> None:
        bp = self._selected()
        if bp is None:
            return
        self._ctx.host.push_screen(BreakpointEditDialog(ctx=self._ctx, breakpoint=bp))

    def _selected(self) -> BreakpointInfo | None:
        row = self.cursor_row
        if row is None or row < 0 or row >= len(self._rows):
            return None
        return self._rows[row]


def _format_breakpoint_details(bp: BreakpointInfo) -> str:
    parts: list[str] = []
    if bp.log_message:
        parts.append(f"log {bp.log_message}")
    if bp.condition:
        parts.append(f"if {bp.condition}")
    if bp.hit_condition:
        parts.append(f"hit {bp.hit_condition}")
    if bp.message:
        parts.append(bp.message)
    return "  •  ".join(parts)


class BreakpointsPanel(Container):
    def __init__(self, *, ctx: AppContext) -> None:
        super().__init__()
        self._ctx = ctx
        self._store = _get_store(ctx)
        self._unsubscribe: Callable[[], None] | None = None
        self._table = BreakpointsTable(ctx=ctx, store=self._store)
        self._last: tuple[BreakpointInfo, ...] = ()

    def compose(self) -> ComposeResult:
        yield self._table

    def on_mount(self) -> None:
        self._unsubscribe = self._store.subscribe(self._on_snapshot)

    def on_unmount(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()

    def _on_snapshot(self, snapshot: SessionSnapshot) -> None:
        if snapshot.breakpoints == self._last:
            return
        self._last = snapshot.breakpoints
        self._table.set_breakpoints(snapshot.breakpoints)


class ConsolePanel(Container):
    def __init__(self, *, ctx: AppContext) -> None:
        super().__init__()
        self._ctx = ctx
        self._tasks: set[asyncio.Task[None]] = set()

    def compose(self) -> ComposeResult:
        yield RichLog(id="console_log", max_lines=300, wrap=True, auto_scroll=True)
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
        log = self.query_one("#console_log", RichLog)
        for line in text.splitlines():
            log.write(line)
