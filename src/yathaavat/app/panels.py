from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import ClassVar, cast

from rich.style import Style
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container, Horizontal
from textual.css.query import NoMatches
from textual.document._document import Document, Selection
from textual.events import MouseDown
from textual.screen import ModalScreen
from textual.strip import Strip
from textual.widgets import DataTable, Input, ListItem, ListView, RichLog, Select, Static, TextArea

from yathaavat.app.breakpoint import BreakpointEditDialog
from yathaavat.app.expression import ExpressionInput
from yathaavat.app.input_history import InputHistory
from yathaavat.app.search import find_next_index, find_prev_index
from yathaavat.app.source_gutter import (
    EXEC_MARKER,
    GutterMarker,
    apply_gutter_marker,
    marker_for_breakpoint,
)
from yathaavat.core import (
    SESSION_MANAGER,
    SESSION_STORE,
    AppContext,
    BreakpointInfo,
    FrameInfo,
    ScopeInfo,
    SessionManager,
    SessionSnapshot,
    SessionStore,
    SetVariableManager,
    VariableInfo,
    VariablePage,
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
        Binding("ctrl+p", "app.open_palette", show=False),
        Binding("ctrl+a", "app.command('session.attach')", show=False),
        Binding("ctrl+k", "app.command('session.connect')", show=False),
        Binding("ctrl+r", "app.command('session.launch')", show=False),
        Binding("ctrl+\\", "app.command('session.disconnect')", show=False),
        Binding("ctrl+shift+\\", "app.command('session.terminate')", show=False),
        Binding("ctrl+f", "app.command('source.find')", show=False),
        Binding("/", "app.command('source.find')", show=False),
        Binding("ctrl+g", "app.command('source.goto')", show=False),
        Binding("ctrl+l", "app.focus_locals", show=False, priority=True),
        Binding("alt+l", "app.focus_locals", show=False, priority=True),
        Binding("ctrl+e", "app.command('source.jump_to_exec')", show=False),
        Binding("ctrl+w", "app.command('watch.add')", show=False),
        Binding("ctrl+b", "app.command('breakpoint.add')", show=False),
        Binding("f2", "app.command('view.zoom')", show=False),
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
        elif show_exec and self._exec_line == line_no:
            strip = apply_gutter_marker(strip, gutter_width=self.gutter_width, marker=EXEC_MARKER)

        if show_exec and self._exec_line == line_no:
            strip = strip.apply_style(Style(bgcolor="#1a4b7a"))

        return strip


class _FindInput(Input):
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+p", "app.open_palette", show=False),
        Binding("escape", "close_find", show=False),
        Binding("f3", "find_next", show=False),
        Binding("shift+f3", "find_prev", show=False),
        Binding("shift+enter", "find_prev", show=False),
    ]

    def __init__(self, *, owner: SourcePanel) -> None:
        super().__init__(placeholder="type to search…", id="find_input")
        self._owner = owner

    def action_close_find(self) -> None:
        self._owner._close_find()

    def action_find_next(self) -> None:
        self._owner._find_in_source(self.value, direction="next", include_current=False)

    def action_find_prev(self) -> None:
        self._owner._find_in_source(self.value, direction="prev", include_current=False)


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
        self._find_open = False
        self._find_task: asyncio.Task[None] | None = None
        self._find_query: str = ""

    def compose(self) -> ComposeResult:
        yield Static("", id="source_header")
        yield CodeView()
        yield Container(
            Horizontal(
                Static("Find", id="find_title"),
                _FindInput(owner=self),
                Static("", id="find_status"),
                id="find_row",
            ),
            Static("Enter next  •  Shift+Enter prev  •  Esc close", id="find_hint"),
            id="find_root",
        )

    def on_mount(self) -> None:
        self._unsubscribe = self._store.subscribe(self._on_snapshot)
        find_root = self.query_one("#find_root", Container)
        find_root.styles.display = "none"

    def on_unmount(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
        if self._find_task is not None:
            self._find_task.cancel()

    def open_find(self) -> None:
        """Open the inline Find bar for the Source panel."""

        find_root = self.query_one("#find_root", Container)
        find_input = self.query_one("#find_input", Input)
        find_hint = self.query_one("#find_hint", Static)
        find_status = self.query_one("#find_status", Static)

        if self._find_open:
            find_root.styles.display = "block"
            find_input.focus()
            find_input.action_select_all()
            return

        self._find_open = True
        find_root.styles.display = "block"
        find_status.update("")
        find_hint.update("Enter next  •  Shift+Enter prev  •  Esc close")

        editor = self.query_one("#source_view", CodeView)
        selection = editor.selected_text
        if selection and not find_input.value and "\n" not in selection:
            find_input.value = selection[:120]
            find_input.action_select_all()
        find_input.focus()

    def _close_find(self) -> None:
        if not self._find_open:
            return
        if self._find_task is not None:
            self._find_task.cancel()
            self._find_task = None
        self._find_query = ""
        self._find_open = False
        find_root = self.query_one("#find_root", Container)
        find_root.styles.display = "none"
        self.query_one("#find_status", Static).update("")
        self.query_one("#find_hint", Static).update("")
        self.query_one("#source_view", CodeView).focus()

    @on(Input.Submitted, "#find_input")
    def _on_find_submit(self, event: Input.Submitted) -> None:
        self._find_in_source(event.value, direction="next", include_current=False)

    @on(Input.Changed, "#find_input")
    def _on_find_changed(self, event: Input.Changed) -> None:
        q = event.value.strip()
        self._find_query = q
        if self._find_task is not None:
            self._find_task.cancel()
            self._find_task = None

        find_hint = self.query_one("#find_hint", Static)
        find_status = self.query_one("#find_status", Static)
        if not q:
            find_hint.update("Enter next  •  Shift+Enter prev  •  Esc close")
            find_status.update("")
            return

        self._find_task = asyncio.create_task(self._find_debounced(q))

    async def _find_debounced(self, query: str) -> None:
        try:
            await asyncio.sleep(0.12)
        except asyncio.CancelledError:
            return

        if not self._find_open:
            return
        current = self.query_one("#find_input", Input).value.strip()
        if current != query:
            return
        self._find_in_source(query, direction="next", include_current=True)

    def _find_in_source(self, query: str, *, direction: str, include_current: bool) -> None:
        q_raw = query.strip()
        if not q_raw:
            return

        editor = self.query_one("#source_view", CodeView)
        text = editor.text or ""
        if not text:
            self._ctx.host.notify("No source text loaded.", timeout=2.0)
            return

        smart_case = any(ch.isupper() for ch in q_raw)
        hay = text if smart_case else text.lower()
        needle = q_raw if smart_case else q_raw.lower()

        doc = editor.document
        if not isinstance(doc, Document):
            self._ctx.host.notify("Search is not available.", timeout=2.0)
            return

        start_index = doc.get_index_from_location(editor.cursor_location)
        if include_current:
            start_index = max(start_index - 1, -1)
        found = (
            find_prev_index(hay, needle, start_index)
            if direction == "prev"
            else find_next_index(hay, needle, start_index)
        )

        find_hint = self.query_one("#find_hint", Static)
        find_status = self.query_one("#find_status", Static)
        if found is None:
            find_hint.update("No matches  •  Esc close")
            find_status.update("0")
            return

        start_loc = doc.get_location_from_index(found)
        end_loc = doc.get_location_from_index(found + len(needle))
        editor.selection = Selection(start_loc, end_loc)
        editor.cursor_location = start_loc
        editor.scroll_to(y=max(start_loc[0] - 6, 0), animate=False, immediate=True)

        total = 0
        ordinal = 0
        pos = 0
        while True:
            idx = hay.find(needle, pos)
            if idx < 0:
                break
            total += 1
            if idx == found:
                ordinal = total
            pos = idx + 1

        find_hint.update("Enter next  •  Shift+Enter prev  •  Esc close")
        loc = f"{start_loc[0] + editor.line_number_start}:{start_loc[1] + 1}"
        if total > 0:
            loc = f"{loc}  {ordinal}/{total}"
        find_status.update(loc)

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
    parent_reference: int | None = None
    load_more_reference: int | None = None
    load_more_start: int | None = None

    @property
    def is_load_more(self) -> bool:
        return self.load_more_reference is not None


class LocalsTable(DataTable[str]):
    BINDINGS: ClassVar[list[BindingType]] = [
        ("enter", "toggle_expand", "Expand"),
        ("/", "focus_filter", "Filter"),
        ("g", "next_scope", "Next Scope"),
        ("e", "edit_value", "Edit"),
        ("y", "copy_value", "Copy Value"),
    ]

    def __init__(self, *, ctx: AppContext, page_size: int = 50) -> None:
        super().__init__(
            id="locals_table",
            cursor_type="row",
            zebra_stripes=True,
            show_row_labels=False,
            cell_padding=0,
        )
        self._ctx = ctx
        self._page_size = page_size
        self._root: tuple[VariableInfo, ...] = ()
        self._root_page: VariablePage | None = None
        self._root_parent_reference: int | None = None
        self._generation: int | None = None
        self._empty_label = "No locals."
        self._expanded: set[int] = set()
        self._cache: dict[int, tuple[VariableInfo, ...]] = {}
        self._pages: dict[int, VariablePage] = {}
        self._visible_counts: dict[int, int] = {}
        self._fetching: dict[int, int] = {}
        self._next_fetch_token = 0
        self._flat: list[_VarNode] = []
        self._filter: str = ""
        self.add_columns("Name", "Type", "Value")

    def set_root(
        self,
        locals_: tuple[VariableInfo, ...],
        *,
        parent_reference: int | None = None,
        root_page: VariablePage | None = None,
        generation: int | None = None,
        empty_label: str = "No locals.",
    ) -> None:
        generation_changed = generation is not None and generation != self._generation
        if (
            locals_ == self._root
            and parent_reference == self._root_parent_reference
            and root_page == self._root_page
            and empty_label == self._empty_label
            and not generation_changed
        ):
            return
        self._empty_label = empty_label
        if generation is not None:
            self._generation = generation
        if not generation_changed and parent_reference == self._root_parent_reference:
            changed_refs = _changed_variable_references(self._root, locals_)
            for ref in changed_refs:
                self._clear_variable_tree(ref)
            self._root = locals_
            self._root_page = root_page
            self._rebuild()
            return
        self._root = locals_
        self._root_page = root_page
        self._root_parent_reference = parent_reference
        self._clear_all_variable_state()
        self._rebuild()

    def _clear_all_variable_state(self) -> None:
        self._expanded.clear()
        self._cache.clear()
        self._pages.clear()
        self._visible_counts.clear()
        self._fetching.clear()
        self._next_fetch_token += 1

    def visible_nodes(self) -> tuple[_VarNode, ...]:
        return tuple(self._flat)

    @property
    def page_size(self) -> int:
        return self._page_size

    def has_loaded_root(self, *, parent_reference: int, generation: int) -> bool:
        return (
            self._root_parent_reference == parent_reference
            and self._generation == generation
            and self._root_page is not None
        )

    def set_filter(self, value: str) -> None:
        next_filter = value.strip().casefold()
        if next_filter == self._filter:
            return
        self._filter = next_filter
        self._rebuild()
        if self._flat and self._filter:
            self.move_cursor(row=self._preferred_filter_row())

    async def action_toggle_expand(self) -> None:
        node = self._selected_node()
        if node is None or node.variables_reference <= 0:
            if node is not None and node.is_load_more:
                await self._load_more(node)
            return

        ref = node.variables_reference
        if ref in self._expanded:
            self._clear_variable_tree(ref)
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
            if ref in self._fetching:
                return
            token = self._begin_fetch(ref)
            try:
                self._ctx.host.notify("Loading variables…", timeout=1.0)
                page = await self.get_variable_page(manager, ref, start=0, count=self._page_size)
                if not self._is_current_fetch(ref, token):
                    return
                self._pages[ref] = page
                self._cache[ref] = page.variables
                self._visible_counts[ref] = min(len(page.variables), self._page_size)
            except Exception as exc:
                self._ctx.host.notify(str(exc), timeout=2.5)
                return
            finally:
                self._finish_fetch(ref, token)

        self._expanded.add(ref)
        self._rebuild()

    @on(DataTable.RowSelected)
    async def _on_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.control is not self:
            return
        await self.action_toggle_expand()

    async def _load_more(self, node: _VarNode) -> None:
        ref = node.load_more_reference
        start = node.load_more_start
        if ref is None or start is None:
            return
        if ref == self._root_parent_reference:
            await self._load_more_root(ref, start)
            return
        current = self._cache.get(ref) or ()
        if start < len(current):
            self._visible_counts[ref] = min(start + self._page_size, len(current))
            self._rebuild()
            return
        if ref in self._fetching:
            return
        manager = _get_manager(self._ctx)
        if not isinstance(manager, VariablesManager):
            self._ctx.host.notify(
                "Variable expansion is not supported by this session.",
                timeout=2.5,
            )
            return
        token = self._begin_fetch(ref)
        try:
            self._ctx.host.notify("Loading variables…", timeout=1.0)
            page = await self.get_variable_page(manager, ref, start=start, count=self._page_size)
            if not self._is_current_fetch(ref, token) or ref not in self._expanded:
                return
        except Exception as exc:
            self._ctx.host.notify(str(exc), timeout=2.5)
            return
        finally:
            self._finish_fetch(ref, token)
        current = self._cache.get(ref) or ()
        new_variables = _new_variables(current, page.variables)
        if len(new_variables) < len(page.variables):
            self._cache[ref] = (*current, *new_variables)
            self._pages[ref] = VariablePage(variables=self._cache[ref])
            self._visible_counts[ref] = len(self._cache[ref])
            self._rebuild()
            return
        self._cache[ref] = (*current, *new_variables)
        self._pages[ref] = page
        self._visible_counts[ref] = len(self._cache[ref])
        self._rebuild()

    async def _load_more_root(self, ref: int, start: int) -> None:
        if start < len(self._root):
            return
        if ref in self._fetching:
            return
        manager = _get_manager(self._ctx)
        if not isinstance(manager, VariablesManager):
            self._ctx.host.notify(
                "Variable expansion is not supported by this session.",
                timeout=2.5,
            )
            return
        token = self._begin_fetch(ref)
        try:
            self._ctx.host.notify("Loading variables…", timeout=1.0)
            page = await self.get_variable_page(manager, ref, start=start, count=self._page_size)
            if not self._is_current_fetch(ref, token):
                return
        except Exception as exc:
            self._ctx.host.notify(str(exc), timeout=2.5)
            return
        finally:
            self._finish_fetch(ref, token)
        new_variables = _new_variables(self._root, page.variables)
        self._root = (*self._root, *new_variables)
        self._root_page = _root_scope_page(self._root, page)
        self._persist_root_update(ref)
        self._rebuild()

    async def get_variable_page(
        self,
        manager: VariablesManager,
        variables_reference: int,
        *,
        start: int,
        count: int,
    ) -> VariablePage:
        try:
            get_page = getattr(manager, "get_variables_page")  # noqa: B009
        except AttributeError:
            get_page = None
        if callable(get_page):
            typed_get_page = cast(
                Callable[..., Awaitable[VariablePage]],
                get_page,
            )
            return await typed_get_page(variables_reference, start=start, count=count)
        variables = await manager.get_variables(variables_reference)
        return VariablePage(variables=variables)

    def action_copy_value(self) -> None:
        node = self._selected_node()
        if node is None or node.is_load_more:
            return
        self.app.copy_to_clipboard(node.value)
        self._ctx.host.notify("Copied value.", timeout=1.2)

    def action_focus_filter(self) -> None:
        try:
            self.query_ancestor(LocalsPanel).focus_filter()
        except NoMatches:
            return

    def action_next_scope(self) -> None:
        try:
            self.query_ancestor(LocalsPanel).next_scope()
        except NoMatches:
            return

    async def action_edit_value(self) -> None:
        node = self._selected_node()
        if node is None or node.is_load_more:
            return
        if node.parent_reference is None:
            self._ctx.host.notify("Root variables cannot be edited here.", timeout=2.5)
            return
        self.app.push_screen(VariableEditDialog(table=self, node=node))

    async def edit_selected_value(self, value: str, *, node: _VarNode | None = None) -> bool:
        node = node or self._selected_node()
        if node is None or node.is_load_more:
            return False
        parent_ref = node.parent_reference
        if parent_ref is None:
            self._ctx.host.notify("Root variables cannot be edited here.", timeout=2.5)
            return False
        manager = _get_manager(self._ctx)
        if not isinstance(manager, SetVariableManager):
            self._ctx.host.notify("Variable editing is not supported by this session.", timeout=2.5)
            return False
        try:
            updated = await manager.set_variable(parent_ref, node.name, value)
        except Exception as exc:
            self._ctx.host.notify(str(exc), timeout=2.5)
            return False
        children = self._cache.get(parent_ref) or ()
        updated_children = tuple(
            updated if child.name == node.name else child for child in children
        )
        if parent_ref == self._root_parent_reference:
            self._root = tuple(
                updated if child.name == node.name else child for child in self._root
            )
            if self._root_page is not None:
                self._root_page = _root_scope_page(self._root, self._root_page)
            self._persist_root_update(parent_ref)
        else:
            self._cache[parent_ref] = updated_children
        if node.variables_reference > 0:
            self._cache.pop(node.variables_reference, None)
            self._pages.pop(node.variables_reference, None)
            self._visible_counts.pop(node.variables_reference, None)
            self._expanded.discard(node.variables_reference)
        self._ctx.host.notify(f"Updated {node.name}.", timeout=1.2)
        self._rebuild()
        return True

    def _persist_root_update(self, parent_ref: int) -> None:
        try:
            store = _get_store(self._ctx)
        except KeyError:
            return
        snapshot = store.snapshot()
        page = self._root_page
        if page is not None:
            page = _root_scope_page(self._root, page)
        scopes = tuple(
            replace(scope, variables=self._root, page=page)
            if scope.variables_reference == parent_ref
            else scope
            for scope in snapshot.scopes
        )
        changes: dict[str, object] = {"scopes": scopes}
        if snapshot.locals_reference == parent_ref:
            changes["locals"] = self._root
        store.update(**changes)

    def _clear_variable_tree(self, ref: int) -> None:
        children = self._cache.pop(ref, None) or ()
        self._expanded.discard(ref)
        self._pages.pop(ref, None)
        self._visible_counts.pop(ref, None)
        self._fetching.pop(ref, None)
        for child in children:
            if child.variables_reference > 0:
                self._clear_variable_tree(child.variables_reference)

    def _begin_fetch(self, ref: int) -> int:
        self._next_fetch_token += 1
        token = self._next_fetch_token
        self._fetching[ref] = token
        return token

    def _is_current_fetch(self, ref: int, token: int) -> bool:
        return self._fetching.get(ref) == token

    def _finish_fetch(self, ref: int, token: int) -> None:
        if self._fetching.get(ref) == token:
            self._fetching.pop(ref, None)

    def _selected_node(self) -> _VarNode | None:
        row = self.cursor_row
        if row is None:
            return None
        if row < 0 or row >= len(self._flat):
            return None
        return self._flat[row]

    def _rebuild(self) -> None:
        selected = self._selected_node()
        selected_key = _node_key(selected) if selected is not None else None
        previous_row = self.cursor_row
        self.clear(columns=False)
        self._flat = []
        if not self._root:
            self.add_row(self._empty_label, "", "")
            return

        def add_vars(
            vars_: tuple[VariableInfo, ...],
            *,
            depth: int,
            parent_reference: int | None,
        ) -> None:
            for v in vars_:
                ref = v.variables_reference
                arrow = " "
                if ref > 0:
                    arrow = "▾" if ref in self._expanded else "▸"
                name = f"{'  ' * depth}{arrow} {v.name}"
                vtype = v.type or ""
                node = _VarNode(
                    name=v.name,
                    value=v.value,
                    type=v.type,
                    variables_reference=ref,
                    depth=depth,
                    parent_reference=parent_reference,
                )
                self._add_node(node, name, vtype, v.value)
                if ref in self._expanded:
                    add_expanded_children(ref, depth=depth + 1)

        def add_expanded_children(ref: int, *, depth: int) -> None:
            children = self._cache.get(ref) or ()
            visible_count = self._visible_counts.get(ref, len(children))
            visible_children = children if self._filter else children[:visible_count]
            add_vars(visible_children, depth=depth, parent_reference=ref)
            page = self._pages.get(ref)
            page_next_start = page.next_start if page is not None else None
            next_start = visible_count if visible_count < len(children) else page_next_start
            if next_start is not None:
                total = page.total if page is not None else None
                total_label = total or (len(children) if visible_count < len(children) else "?")
                load_node = _VarNode(
                    name="Load more...",
                    value=f"{next_start}/{total_label} loaded",
                    type="",
                    variables_reference=0,
                    depth=depth,
                    load_more_reference=ref,
                    load_more_start=next_start,
                )
                self._add_node(
                    load_node,
                    f"{'  ' * depth}… Load more...",
                    "",
                    load_node.value,
                )

        add_vars(self._root, depth=0, parent_reference=self._root_parent_reference)
        if self._root_parent_reference is not None and self._root_page is not None:
            next_start = self._root_page.next_start
            if next_start is not None:
                total = self._root_page.total
                total_label = total or "?"
                load_node = _VarNode(
                    name="Load more...",
                    value=f"{next_start}/{total_label} loaded",
                    type="",
                    variables_reference=0,
                    depth=0,
                    load_more_reference=self._root_parent_reference,
                    load_more_start=next_start,
                )
                self._add_node(load_node, "… Load more...", "", load_node.value)
        if self._filter and not self._flat:
            self.add_row("No matching variables.", "", "")
        self._restore_cursor(selected_key, previous_row)

    def _add_node(self, node: _VarNode, name: str, type_: str, value: str) -> None:
        if self._filter and not node.is_load_more and not _node_matches_filter(node, self._filter):
            return
        self.add_row(name, type_, value)
        self._flat.append(node)

    def _restore_cursor(
        self,
        selected_key: tuple[object, ...] | None,
        previous_row: int | None,
    ) -> None:
        if not self._flat:
            return
        if selected_key is not None:
            for index, node in enumerate(self._flat):
                if _node_key(node) == selected_key:
                    self.move_cursor(row=index)
                    return
        if previous_row is not None:
            self.move_cursor(row=min(max(previous_row, 0), len(self._flat) - 1))

    def _preferred_filter_row(self) -> int:
        for index, node in enumerate(self._flat):
            if (
                not node.is_load_more
                and node.depth > 0
                and node.parent_reference is not None
                and _node_matches_filter(node, self._filter)
            ):
                return index
        for index, node in enumerate(self._flat):
            if (
                not node.is_load_more
                and node.parent_reference is not None
                and _node_matches_filter(node, self._filter)
            ):
                return index
        for index, node in enumerate(self._flat):
            if not node.is_load_more and _node_matches_filter(node, self._filter):
                return index
        return 0


def _node_key(node: _VarNode) -> tuple[object, ...]:
    return (
        node.name,
        node.depth,
        node.parent_reference,
        node.variables_reference,
        node.load_more_reference,
        node.load_more_start,
    )


def _node_matches_filter(node: _VarNode, query: str) -> bool:
    hay = " ".join(part for part in (node.name, node.type or "", node.value) if part)
    return query in hay.casefold()


def _new_variables(
    current: tuple[VariableInfo, ...],
    incoming: tuple[VariableInfo, ...],
) -> tuple[VariableInfo, ...]:
    if not current or not incoming:
        return incoming
    current_names = {variable.name for variable in current}
    return tuple(variable for variable in incoming if variable.name not in current_names)


def _root_scope_page(
    variables: tuple[VariableInfo, ...],
    page: VariablePage,
) -> VariablePage:
    count = len(variables)
    if page.total is None and page.count is not None and len(page.variables) < page.count:
        count = len(variables) + 1
    return VariablePage(
        variables=variables,
        start=0,
        count=count,
        filter=page.filter,
        indexed_variables=page.indexed_variables,
        named_variables=page.named_variables,
    )


def _changed_variable_references(
    old: tuple[VariableInfo, ...], new: tuple[VariableInfo, ...]
) -> tuple[int, ...]:
    old_by_name = {v.name: v for v in old}
    changed: list[int] = []
    for current in new:
        previous = old_by_name.get(current.name)
        if previous is None:
            continue
        if previous != current and previous.variables_reference > 0:
            changed.append(previous.variables_reference)
    return tuple(changed)


def _locals_page_size() -> int:
    raw = os.environ.get("YATHAAVAT_VARIABLE_PAGE_SIZE", "")
    try:
        parsed = int(raw)
    except ValueError:
        return 50
    return min(max(parsed, 1), 500)


class VariableEditDialog(ModalScreen[None]):
    BINDINGS: ClassVar[list[BindingType]] = [("escape", "app.pop_screen", "Close")]

    def __init__(self, *, table: LocalsTable, node: _VarNode) -> None:
        super().__init__()
        self._table = table
        self._node = node
        self._submitting = False

    def compose(self) -> ComposeResult:
        yield Container(
            Static(f"Edit {self._node.name}", id="var_title"),
            Input(value=self._node.value, id="var_input"),
            Static("Enter update • Esc close", id="var_hint"),
            id="var_root",
        )

    def on_mount(self) -> None:
        input_ = self.query_one("#var_input", Input)
        input_.focus()
        input_.action_select_all()

    @on(Input.Submitted, "#var_input")
    async def _on_submit(self, event: Input.Submitted) -> None:
        if self._submitting:
            return
        self._submitting = True
        updated = await self._table.edit_selected_value(event.value, node=self._node)
        if updated:
            self.app.pop_screen()
            return
        self._submitting = False
        self.query_one("#var_input", Input).focus()


class _LocalsFilterInput(Input):
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("enter", "focus_table", "Focus locals", show=False),
        Binding("escape", "clear_filter", "Clear", show=False),
    ]

    def _panel(self) -> LocalsPanel | None:
        try:
            return self.query_ancestor(LocalsPanel)
        except NoMatches:
            return None

    def action_focus_table(self) -> None:
        panel = self._panel()
        if panel is not None:
            panel.focus_table()

    def action_clear_filter(self) -> None:
        self.value = ""
        self.action_focus_table()

    def on_input_changed(self, event: Input.Changed) -> None:
        panel = self._panel()
        if panel is not None:
            panel.apply_filter(event.value)


class LocalsPanel(Container):
    def __init__(self, *, ctx: AppContext) -> None:
        super().__init__()
        self._ctx = ctx
        self._store = _get_store(ctx)
        self._unsubscribe: Callable[[], None] | None = None
        self._table = LocalsTable(ctx=ctx, page_size=_locals_page_size())
        self._scopes: tuple[ScopeInfo, ...] = ()
        self._selected_scope_name: str | None = None
        self._variables_generation: int | None = None
        self._syncing_scope = False
        self._scope_task: asyncio.Task[None] | None = None
        self._scope_task_key: tuple[str, int] | None = None
        self._scope_option_names: tuple[str, ...] = ()

    def compose(self) -> ComposeResult:
        yield Select[str]((), prompt="Scope", allow_blank=True, id="scope_select", compact=True)
        yield _LocalsFilterInput(placeholder="filter locals…", id="locals_filter")
        yield self._table

    def on_mount(self) -> None:
        self._unsubscribe = self._store.subscribe(self._on_snapshot)

    def on_unmount(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
        if self._scope_task is not None:
            self._scope_task.cancel()

    def _on_snapshot(self, snapshot: SessionSnapshot) -> None:
        self._scopes = snapshot.scopes
        selected = self._selected_scope_name
        if snapshot.scopes:
            scope_names = {scope.name for scope in snapshot.scopes}
            if selected not in scope_names:
                selected = snapshot.selected_scope_name or snapshot.scopes[0].name
            if selected is None:
                selected = snapshot.scopes[0].name
        else:
            selected = None
        material_changed = (
            snapshot.variables_generation != self._variables_generation
            or selected != self._selected_scope_name
        )
        self._sync_scope_select(snapshot, selected)
        if not snapshot.scopes:
            self._variables_generation = snapshot.variables_generation
            self._selected_scope_name = None
            self._cancel_scope_task()
            self._table.set_root(
                snapshot.locals,
                parent_reference=snapshot.locals_reference,
                generation=snapshot.variables_generation,
            )
            return
        if not material_changed:
            return
        self._variables_generation = snapshot.variables_generation

        if selected is None:
            return
        self._show_scope(snapshot, selected)

    def _sync_scope_select(self, snapshot: SessionSnapshot, selected: str | None = None) -> None:
        select = self.query_one("#scope_select", Select)
        self._syncing_scope = True
        try:
            if not snapshot.scopes:
                if self._scope_option_names:
                    select.set_options(())
                    self._scope_option_names = ()
                select.disabled = True
                return
            options = tuple((scope.name, scope.name) for scope in snapshot.scopes)
            option_names = tuple(scope.name for scope in snapshot.scopes)
            if option_names != self._scope_option_names:
                select.set_options(options)
                self._scope_option_names = option_names
            select.disabled = False
            selected = selected or self._selected_scope_name
            if selected not in {scope.name for scope in snapshot.scopes}:
                selected = snapshot.selected_scope_name or snapshot.scopes[0].name
            select.value = selected
        finally:
            self._syncing_scope = False

    @on(Select.Changed, "#scope_select")
    def _on_scope_changed(self, event: Select.Changed) -> None:
        if self._syncing_scope:
            return
        if not isinstance(event.value, str):
            return
        snapshot = self._store.snapshot()
        self._show_scope(snapshot, event.value)

    def _show_scope(self, snapshot: SessionSnapshot, name: str) -> None:
        scope = next((s for s in snapshot.scopes if s.name == name), None)
        if scope is None:
            return
        if (
            self._selected_scope_name == scope.name
            and self._variables_generation == snapshot.variables_generation
            and self._table.has_loaded_root(
                parent_reference=scope.variables_reference,
                generation=snapshot.variables_generation,
            )
        ):
            return
        if (
            self._selected_scope_name == scope.name
            and self._scope_task is not None
            and not self._scope_task.done()
            and self._scope_task_key == (scope.name, snapshot.variables_generation)
        ):
            return
        self._selected_scope_name = scope.name
        if snapshot.selected_scope_name != scope.name:
            self._store.update(selected_scope_name=scope.name)
            snapshot = self._store.snapshot()
        variables = (
            snapshot.locals
            if snapshot.locals_reference == scope.variables_reference
            else scope.variables
        )
        page = scope.page
        if page is not None:
            variables = page.variables
        elif variables:
            page = VariablePage(
                variables=variables,
                start=0,
                count=len(variables),
                indexed_variables=scope.indexed_variables,
                named_variables=scope.named_variables,
            )
        if page is not None:
            self._cancel_scope_task()
            self._table.set_root(
                variables,
                parent_reference=scope.variables_reference,
                root_page=page,
                generation=snapshot.variables_generation,
                empty_label=f"No {scope.name} variables.",
            )
            return

        self._table.set_root(
            (),
            parent_reference=scope.variables_reference,
            generation=snapshot.variables_generation,
            empty_label=f"Loading {scope.name} variables...",
        )
        self._load_scope(scope, snapshot.variables_generation)

    def _load_scope(self, scope: ScopeInfo, generation: int) -> None:
        key = (scope.name, generation)
        if self._scope_task is not None and not self._scope_task.done():
            if self._scope_task_key == key:
                return
        self._cancel_scope_task()
        manager = _get_manager(self._ctx)
        if not isinstance(manager, VariablesManager):
            self._table.set_root(
                (),
                parent_reference=scope.variables_reference,
                generation=generation,
                empty_label=f"No {scope.name} variables.",
            )
            return

        async def run() -> None:
            try:
                page = await self._table.get_variable_page(
                    manager,
                    scope.variables_reference,
                    start=0,
                    count=self._table.page_size,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._ctx.host.notify(str(exc), timeout=2.5)
                return
            if self._variables_generation != generation or self._selected_scope_name != scope.name:
                return
            root_page = _root_scope_page(page.variables, page)
            self._persist_scope_page(scope, root_page)
            self._table.set_root(
                page.variables,
                parent_reference=scope.variables_reference,
                root_page=root_page,
                generation=generation,
                empty_label=f"No {scope.name} variables.",
            )

        self._scope_task_key = key
        self._scope_task = asyncio.create_task(run())

    def _persist_scope_page(self, scope: ScopeInfo, page: VariablePage) -> None:
        snapshot = self._store.snapshot()
        scopes = tuple(
            replace(existing, variables=page.variables, page=page)
            if existing.variables_reference == scope.variables_reference
            else existing
            for existing in snapshot.scopes
        )
        changes: dict[str, object] = {"scopes": scopes}
        if snapshot.locals_reference == scope.variables_reference:
            changes["locals"] = page.variables
        self._store.update(**changes)

    def _cancel_scope_task(self) -> None:
        if self._scope_task is not None:
            self._scope_task.cancel()
            self._scope_task = None
            self._scope_task_key = None

    def apply_filter(self, value: str) -> None:
        self._table.set_filter(value)

    def focus_table(self) -> None:
        self._table.focus()

    def focus_filter(self) -> None:
        self.query_one("#locals_filter", Input).focus()

    def next_scope(self) -> None:
        if len(self._scopes) < 2:
            return
        current = self._selected_scope_name or self._scopes[0].name
        names = [scope.name for scope in self._scopes]
        try:
            index = names.index(current)
        except ValueError:
            index = -1
        next_name = names[(index + 1) % len(names)]
        select = self.query_one("#scope_select", Select)
        self._syncing_scope = True
        try:
            select.value = next_name
        finally:
            self._syncing_scope = False
        self._show_scope(self._store.snapshot(), next_name)


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
        # Avoid surprising "stale Source" jumps when the Breakpoints table rerenders due to
        # session changes (connect/disconnect). Only sync the Source cursor when the user is
        # actively focused in this table.
        if not self.has_focus:
            return
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
        self._history = InputHistory()

    def compose(self) -> ComposeResult:
        yield RichLog(id="console_log", max_lines=300, wrap=True, auto_scroll=True)
        yield Horizontal(
            Static(">>>", id="console_prompt"),
            ExpressionInput(ctx=self._ctx, history=self._history, id="console_input"),
            id="console_row",
        )

    @on(ExpressionInput.Submitted, "#console_input")
    def _on_submit(self, event: ExpressionInput.Submitted) -> None:
        expr = event.text.strip()
        control = event.control
        if isinstance(control, ExpressionInput):
            control.clear()
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
