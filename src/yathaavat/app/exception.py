from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Container
from textual.widgets import Static, TabbedContent, Tree
from textual.widgets._tree import TreeNode

from yathaavat.core import (
    SESSION_MANAGER,
    SESSION_STORE,
    AppContext,
    ExceptionInfo,
    ExceptionNode,
    ExceptionRelation,
    SessionManager,
    SessionSnapshot,
    SessionStore,
    TracebackFrame,
)


def _get_store(ctx: AppContext) -> SessionStore:
    return ctx.services.get(SESSION_STORE)


def _get_manager(ctx: AppContext) -> SessionManager | None:
    try:
        return ctx.services.get(SESSION_MANAGER)
    except KeyError:
        return None


class ExceptionTree(Tree[TracebackFrame | None]):
    BINDINGS: ClassVar[list[BindingType]] = [
        ("y", "copy_traceback", "Copy Traceback"),
        ("a", "add_breakpoint", "Breakpoint"),
    ]

    def __init__(self, *, ctx: AppContext) -> None:
        super().__init__("Exception", id="exc_tree")
        self._ctx = ctx
        self._info: ExceptionInfo | None = None
        self._tasks: set[asyncio.Task[None]] = set()

    def set_info(self, info: ExceptionInfo | None) -> None:
        self._info = info

    def action_copy_traceback(self) -> None:
        if self._info is None or not self._info.stack_trace:
            self._ctx.host.notify("No traceback to copy.", timeout=1.5)
            return
        self.app.copy_to_clipboard(self._info.stack_trace)
        self._ctx.host.notify("Copied traceback.", timeout=1.2)

    def action_add_breakpoint(self) -> None:
        node = self.cursor_node
        if node is None:
            return
        frame = node.data
        if not isinstance(frame, TracebackFrame):
            return
        if frame.path is None or frame.line is None:
            self._ctx.host.notify("No source location.", timeout=1.5)
            return
        manager = _get_manager(self._ctx)
        if manager is None:
            self._ctx.host.notify("No session.", timeout=1.5)
            return

        path = frame.path
        line = frame.line

        async def _toggle() -> None:
            try:
                await manager.toggle_breakpoint(path, line)
            except Exception as exc:
                self._ctx.host.notify(str(exc), timeout=2.5)

        task = asyncio.create_task(_toggle())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def on_tree_node_selected(self, event: Tree.NodeSelected[TracebackFrame | None]) -> None:
        frame = event.node.data
        if not isinstance(frame, TracebackFrame):
            return
        if frame.path is None or frame.line is None:
            return
        self._jump_to_frame(frame)

    def _jump_to_frame(self, frame: TracebackFrame) -> None:
        store = _get_store(self._ctx)
        snap = store.snapshot()
        manager = _get_manager(self._ctx)

        # Try to find a matching FrameInfo to use select_frame (keeps Locals in sync).
        resolved: str | None = None
        if frame.path:
            try:
                resolved = str(Path(frame.path).expanduser().resolve())
            except OSError:
                resolved = frame.path

        matching_frame_id: int | None = None
        for f in snap.frames:
            f_resolved: str | None = None
            if f.path:
                try:
                    f_resolved = str(Path(f.path).expanduser().resolve())
                except OSError:
                    f_resolved = f.path
            if f_resolved == resolved and f.line == frame.line:
                matching_frame_id = f.id
                break

        if matching_frame_id is not None and manager is not None:

            async def _select() -> None:
                try:
                    await manager.select_frame(matching_frame_id)
                except Exception as exc:
                    self._ctx.host.notify(str(exc), timeout=2.5)

            task = asyncio.create_task(_select())
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        else:
            # Fallback: just navigate Source.
            store.update(
                source_path=frame.path,
                source_line=frame.line,
                source_col=1,
            )


class ExceptionPanel(Container):
    def __init__(self, *, ctx: AppContext) -> None:
        super().__init__()
        self._ctx = ctx
        self._store = _get_store(ctx)
        self._unsubscribe: Callable[[], None] | None = None
        self._last_info: ExceptionInfo | None = None
        self._tree = ExceptionTree(ctx=ctx)

    def compose(self) -> ComposeResult:
        yield Static("No exception.", id="exc_header")
        yield self._tree

    def on_mount(self) -> None:
        self._unsubscribe = self._store.subscribe(self._on_snapshot)

    def on_unmount(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()

    def _on_snapshot(self, snapshot: SessionSnapshot) -> None:
        info = snapshot.exception_info
        if info is self._last_info:
            return
        was_none = self._last_info is None
        self._last_info = info
        self._tree.set_info(info)
        self._update_view(info)
        if info is not None and was_none:
            self.call_later(self._activate_tab)

    def _update_view(self, info: ExceptionInfo | None) -> None:
        header = self.query_one("#exc_header", Static)
        tree = self._tree
        tree.clear()
        if info is None:
            header.update("No exception.")
            return
        header.update(f"[bold red]{info.exception_id}[/]: {info.tree.message}")
        self._build_tree(tree.root, info.tree)
        tree.root.expand_all()

    def _build_tree(self, parent: TreeNode[TracebackFrame | None], node: ExceptionNode) -> None:
        # Build label with relationship prefix.
        label = _node_label(node)
        if node.frames or node.children:
            branch = parent.add(label, data=None)
            for frame in node.frames:
                frame_label = _frame_label(frame)
                branch.add_leaf(frame_label, data=frame)
            for child in node.children:
                self._build_tree(branch, child)
        else:
            # Leaf node: just the exception line (no frames).
            parent.add_leaf(label, data=None)

    def _activate_tab(self) -> None:
        tc = self._find_tabbed_content()
        if tc is not None:
            tc.active = "pane_builtin_exception"

    def _find_tabbed_content(self) -> TabbedContent | None:
        w = self.parent
        while w is not None:
            if isinstance(w, TabbedContent):
                return w
            w = getattr(w, "parent", None)
        return None


def _node_label(node: ExceptionNode) -> str:
    prefix = ""
    match node.relation:
        case ExceptionRelation.CAUSE:
            prefix = "↳ caused by: "
        case ExceptionRelation.CONTEXT:
            prefix = "↳ during handling: "
        case ExceptionRelation.GROUP_MEMBER:
            prefix = ""
        case _:
            prefix = ""
    type_msg = f"{node.type_name}: {node.message}" if node.message else node.type_name
    return f"{prefix}{type_msg}"


def _frame_label(frame: TracebackFrame) -> str:
    parts: list[str] = []
    if frame.path and frame.line:
        parts.append(f"{Path(frame.path).name}:{frame.line}")
    elif frame.path:
        parts.append(Path(frame.path).name)
    parts.append(frame.name)
    if frame.text:
        parts.append(f"# {frame.text.strip()}")
    return "  ".join(parts)
