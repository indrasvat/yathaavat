"""Tasks panel: live asyncio task inspector.

Flat view renders a single-pane DataTable with Name / State / Coroutine /
Location / Awaiting columns. Tree view renders the await graph as a Textual
Tree widget where a node's children are the tasks it is waiting on.

The panel is cooperative with the existing Source / Locals integration: a
selected task's top suspended frame becomes the Source cursor, delegating
via :class:`~yathaavat.core.TaskIntrospectionManager`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import ClassVar

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container
from textual.widgets import DataTable, Static, Tree
from textual.widgets.tree import TreeNode

from yathaavat.core import (
    SESSION_MANAGER,
    SESSION_STORE,
    AppContext,
    SessionSnapshot,
    SessionStore,
    TaskCaptureStatus,
    TaskGraphInfo,
    TaskInfo,
    TaskIntrospectionManager,
    TaskNode,
    TaskState,
    TaskViewMode,
)
from yathaavat.core.asyncio_tasks import (
    find_task,
    format_awaiting_summary,
    format_coroutine_label,
    format_location,
    format_state_marker,
    format_task_detail,
    task_top_location,
)

_STATE_STYLE: dict[TaskState, str] = {
    TaskState.PENDING: "bold #8be9fd",
    TaskState.DONE: "#7cfc9a",
    TaskState.CANCELLED: "#f1c40f",
    TaskState.FAILED: "bold #ff6b6b",
}

_STATUS_HINT: dict[TaskCaptureStatus, str] = {
    TaskCaptureStatus.OK: "",
    TaskCaptureStatus.EMPTY: "No asyncio tasks.",
    TaskCaptureStatus.UNSUPPORTED: "Target does not expose asyncio tasks.",
    TaskCaptureStatus.UNAVAILABLE: "Task capture unavailable on this backend.",
    TaskCaptureStatus.PARTIAL: "Showing partial results — some tasks could not be captured.",
    TaskCaptureStatus.ERROR: "Task capture failed.",
}


def _get_store(ctx: AppContext) -> SessionStore:
    return ctx.services.get(SESSION_STORE)


def _get_manager(ctx: AppContext) -> TaskIntrospectionManager | None:
    try:
        manager = ctx.services.get(SESSION_MANAGER)
    except KeyError:
        return None
    return manager if isinstance(manager, TaskIntrospectionManager) else None


def _state_cell(task: TaskInfo) -> Text:
    style = _STATE_STYLE.get(task.state, "")
    marker = format_state_marker(task)
    return Text(f"{marker} {task.state.value}", style=style)


def _name_cell(task: TaskInfo) -> str:
    return task.name or task.id


def _status_message(graph: TaskGraphInfo | None) -> str:
    if graph is None:
        return "Pause to capture tasks."
    if graph.status is TaskCaptureStatus.OK and graph.tasks:
        return f"{len(graph.tasks)} task(s)"
    hint = _STATUS_HINT.get(graph.status, "")
    if graph.message:
        return f"{hint}  —  {graph.message}" if hint else graph.message
    return hint or "No tasks."


class _TasksTable(DataTable[object]):
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("enter", "jump_to_source", "Jump to source", show=False),
    ]

    def __init__(self, *, panel: TasksPanel) -> None:
        super().__init__(
            id="tasks_table",
            cursor_type="row",
            zebra_stripes=True,
            show_row_labels=False,
            cell_padding=0,
        )
        self._panel = panel
        self._rows: list[TaskInfo] = []
        self.add_columns("Name", "State", "Coroutine", "Location", "Awaiting")

    def set_tasks(self, graph: TaskGraphInfo | None) -> None:
        self.clear(columns=False)
        self._rows = list(graph.tasks) if graph is not None else []
        if not self._rows:
            return
        for task in self._rows:
            self.add_row(
                _name_cell(task),
                _state_cell(task),
                format_coroutine_label(task),
                format_location(task),
                format_awaiting_summary(task, graph) if graph is not None else "",
                key=task.id,
            )

    def selected_task(self) -> TaskInfo | None:
        row = self.cursor_row
        if row is None or row < 0 or row >= len(self._rows):
            return None
        return self._rows[row]

    def focus_task(self, task_id: str | None) -> None:
        if task_id is None:
            return
        for idx, task in enumerate(self._rows):
            if task.id == task_id:
                self.move_cursor(row=idx)
                return

    async def action_jump_to_source(self) -> None:
        task = self.selected_task()
        if task is None:
            return
        await self._panel._activate_task(task)


class _TasksTree(Tree[TaskInfo]):
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("enter", "jump_to_source", "Jump to source", show=False),
    ]

    def __init__(self, *, panel: TasksPanel) -> None:
        super().__init__("Tasks", id="tasks_tree")
        self._panel = panel
        self.show_root = False
        self.guide_depth = 2
        self._by_id: dict[str, TaskInfo] = {}

    def set_graph(self, graph: TaskGraphInfo | None) -> None:
        self.clear()
        self._by_id = {t.id: t for t in graph.tasks} if graph is not None else {}
        if graph is None:
            return
        for node in graph.roots:
            self._add_task_node(self.root, node)
        self.root.expand_all()

    def _add_task_node(self, parent: TreeNode[TaskInfo], node: TaskNode) -> None:
        task = self._by_id.get(node.task_id)
        label = self._format_label(task, node)
        data = task
        if node.children:
            tree_node = parent.add(label, data=data, expand=True)
            for child in node.children:
                self._add_task_node(tree_node, child)
        else:
            parent.add_leaf(label, data=data)

    def _format_label(self, task: TaskInfo | None, node: TaskNode) -> Text:
        if task is None:
            return Text(f"{node.task_id}  (unknown)", style="dim")
        label = Text.assemble(
            _state_cell(task),
            Text("  "),
            Text(task.name, style="bold"),
            Text("  "),
            Text(format_coroutine_label(task), style="dim"),
        )
        if node.cycle_to is not None:
            label.append(Text(f"  ↻ cycle → {node.cycle_to}", style="bold #f1c40f"))
        else:
            loc = format_location(task)
            if loc != "—":
                label.append(Text(f"  @{loc}", style="dim"))
        return label

    def selected_task(self) -> TaskInfo | None:
        node = self.cursor_node
        if node is None:
            return None
        data = node.data
        return data if isinstance(data, TaskInfo) else None

    def focus_task(self, task_id: str | None) -> None:
        if task_id is None:
            return

        def walk(node: TreeNode[TaskInfo]) -> TreeNode[TaskInfo] | None:
            if isinstance(node.data, TaskInfo) and node.data.id == task_id:
                return node
            for child in node.children:
                found = walk(child)
                if found is not None:
                    return found
            return None

        match = walk(self.root)
        if match is not None:
            self.select_node(match)

    async def action_jump_to_source(self) -> None:
        task = self.selected_task()
        if task is None:
            return
        await self._panel._activate_task(task)


class TasksPanel(Container):
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("t", "toggle_mode", "Toggle flat/tree", show=True),
        Binding("r", "refresh", "Refresh", show=True),
    ]

    DEFAULT_CSS = """
    TasksPanel { layout: vertical; }
    TasksPanel > #tasks_status {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    TasksPanel > #tasks_empty {
        height: 1fr;
        content-align: center middle;
        color: $text-muted;
    }
    TasksPanel > DataTable,
    TasksPanel > Tree {
        height: 1fr;
    }
    TasksPanel > #tasks_detail {
        height: 8;
        padding: 0 1;
        background: $surface;
        color: $text;
    }
    """

    def __init__(self, *, ctx: AppContext) -> None:
        super().__init__()
        self._ctx = ctx
        self._store = _get_store(ctx)
        self._unsubscribe: Callable[[], None] | None = None
        self._pending: set[asyncio.Task[None]] = set()
        self._status = Static("", id="tasks_status")
        self._table = _TasksTable(panel=self)
        self._tree = _TasksTree(panel=self)
        self._empty = Static("", id="tasks_empty")
        self._detail = Static("", id="tasks_detail", markup=False)
        self._mode: TaskViewMode = TaskViewMode.FLAT

    def compose(self) -> ComposeResult:
        yield self._status
        yield self._empty
        yield self._table
        yield self._tree
        yield self._detail

    def on_mount(self) -> None:
        self._unsubscribe = self._store.subscribe(self._on_snapshot)
        self._apply_mode(self._mode)

    def on_unmount(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
        self._unsubscribe = None

    def action_toggle_mode(self) -> None:
        new_mode = TaskViewMode.TREE if self._mode is TaskViewMode.FLAT else TaskViewMode.FLAT
        self._mode = new_mode
        self._store.update(task_view_mode=new_mode)
        self._apply_mode(new_mode)
        snap = self._store.snapshot()
        self._render_snapshot(snap)

    def action_refresh(self) -> None:
        manager = _get_manager(self._ctx)
        if manager is None:
            self._ctx.host.notify("Task capture unavailable on this backend.", timeout=2.0)
            return
        self._spawn(manager.refresh_tasks())

    def _apply_mode(self, mode: TaskViewMode) -> None:
        table_visible = mode is TaskViewMode.FLAT
        self._table.display = table_visible
        self._tree.display = not table_visible

    def _on_snapshot(self, snapshot: SessionSnapshot) -> None:
        if snapshot.task_view_mode is not self._mode:
            self._mode = snapshot.task_view_mode
            self._apply_mode(self._mode)
        self._render_snapshot(snapshot)

    def _render_snapshot(self, snapshot: SessionSnapshot) -> None:
        graph = snapshot.task_graph
        self._status.update(_status_message(graph))

        has_tasks = graph is not None and bool(graph.tasks)
        show_empty = not has_tasks
        self._empty.display = show_empty
        self._detail.display = not show_empty
        if self._mode is TaskViewMode.FLAT:
            self._table.display = not show_empty
            self._tree.display = False
        else:
            self._table.display = False
            self._tree.display = not show_empty

        if show_empty:
            self._empty.update(self._empty_label(graph))
            self._detail.update("")
            return

        assert graph is not None
        self._table.set_tasks(graph)
        self._tree.set_graph(graph)
        self._table.focus_task(snapshot.selected_task_id)
        self._tree.focus_task(snapshot.selected_task_id)
        selected = find_task(graph, snapshot.selected_task_id) or graph.tasks[0]
        self._detail.update(format_task_detail(selected, graph))

    def _empty_label(self, graph: TaskGraphInfo | None) -> str:
        if graph is None:
            return "Pause the target to capture asyncio tasks.\nPress r to refresh."
        hint = _STATUS_HINT.get(graph.status, "No asyncio tasks.")
        if graph.message:
            return f"{hint}\n{graph.message}"
        if graph.status is TaskCaptureStatus.EMPTY:
            return f"{hint}\nPress r to refresh."
        return hint

    async def _activate_task(self, task: TaskInfo) -> None:
        manager = _get_manager(self._ctx)
        if manager is not None:
            try:
                await manager.select_task(task.id)
            except Exception as exc:
                self._ctx.host.notify(str(exc), timeout=2.5)
            return

        # No backend support: at least update the Source cursor + selection locally.
        path, line = task_top_location(task)
        if path is None:
            self._ctx.host.notify("Task has no source location.", timeout=2.0)
            return
        self._store.update(
            selected_task_id=task.id,
            source_path=path,
            source_line=line,
            source_col=1,
        )

    @on(DataTable.RowSelected, "#tasks_table")
    def _on_row_selected(self, event: DataTable.RowSelected) -> None:
        task = self._table.selected_task()
        if task is not None:
            self._spawn(self._activate_task(task))

    @on(Tree.NodeSelected)
    def _on_tree_node(self, event: Tree.NodeSelected[TaskInfo]) -> None:
        data = event.node.data
        if isinstance(data, TaskInfo):
            self._spawn(self._activate_task(data))

    def _spawn(self, coro: Callable[[], object] | object) -> None:
        if not asyncio.iscoroutine(coro):
            return
        task = asyncio.create_task(coro)
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)
