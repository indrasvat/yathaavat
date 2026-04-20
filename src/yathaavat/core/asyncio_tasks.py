"""Normalization + graph construction for asyncio task snapshots.

The target-side collector (see ``TASK_COLLECTOR_SOURCE``) serializes live
asyncio tasks into a plain JSON payload. This module converts that payload
into the domain types (:class:`TaskInfo`, :class:`TaskGraphInfo`) the TUI
consumes, and provides helpers for presentation.

Design notes
------------

* The collector must never raise into the debugger; partial/best-effort
  results are preferred over complete failure. Parsing here mirrors that
  stance — missing fields degrade to sensible defaults.
* Tree construction uses the ``awaited_by`` edges: tasks with an empty
  ``awaited_by`` list are roots, and a task's children are the tasks it is
  awaiting. Cycles are detected and surfaced as ``TaskNode.cycle_to``
  markers rather than causing infinite recursion.
* Rendering helpers are pure functions so they can be unit-tested without
  Textual.
"""

from __future__ import annotations

import json
from pathlib import Path

from yathaavat.core.session import (
    TaskCaptureStatus,
    TaskGraphInfo,
    TaskInfo,
    TaskNode,
    TaskStackFrame,
    TaskState,
)

__all__ = [
    "TASK_COLLECTOR_SOURCE",
    "build_task_graph",
    "find_task",
    "format_awaiting_summary",
    "format_coroutine_label",
    "format_location",
    "format_state_marker",
    "parse_collector_payload",
    "task_top_location",
]


TASK_COLLECTOR_SOURCE = r"""
def __yathaavat_collect_async_tasks__():
    import asyncio
    import gc
    import json
    import traceback

    def _safe(fn, default):
        try:
            return fn()
        except Exception:
            return default

    def _coro_label(coro):
        if coro is None:
            return ""
        qual = getattr(coro, "__qualname__", None) or getattr(coro, "__name__", None)
        if qual:
            return str(qual)
        return _safe(lambda: repr(coro), "<coroutine>")

    def _frame_entry(frame):
        code = getattr(frame, "f_code", None)
        return {
            "name": getattr(code, "co_name", "") if code else "",
            "path": getattr(code, "co_filename", None) if code else None,
            "line": getattr(frame, "f_lineno", None),
        }

    def _state(task):
        if _safe(task.cancelled, False):
            return "cancelled"
        if not _safe(task.done, False):
            return "pending"
        if _safe(lambda: task.exception() is not None, False):
            return "failed"
        return "done"

    def _stack(task, limit=12):
        frames = _safe(lambda: task.get_stack(limit=limit), [])
        return [_frame_entry(f) for f in frames]

    def _exception(task):
        if not _safe(task.done, False) or _safe(task.cancelled, False):
            return None
        exc = _safe(task.exception, None)
        if exc is None:
            return None
        return "{}: {}".format(type(exc).__name__, exc)

    def _await_graph(task):
        fn = getattr(asyncio, "capture_call_graph", None)
        if fn is None:
            return None
        try:
            return fn(task)
        except Exception:
            return None

    def _collect():
        tasks = []
        seen = set()
        for obj in gc.get_objects():
            if isinstance(obj, asyncio.Task) and id(obj) not in seen:
                seen.add(id(obj))
                tasks.append(obj)

        by_id = {id(t): t for t in tasks}
        out = []
        awaited_by = {id(t): [] for t in tasks}
        for t in tasks:
            stack = _stack(t)
            top = stack[0] if stack else {"name": "", "path": None, "line": None}
            coro = _safe(t.get_coro, None)
            graph = _await_graph(t)
            awaiting_ids = []
            seen_edge = set()
            if graph is not None:
                pending = list(_safe(lambda g=graph: list(g.awaited_by), []))
                while pending:
                    entry = pending.pop(0)
                    fut = _safe(lambda e=entry: e.future, None)
                    if isinstance(fut, asyncio.Task) and id(fut) != id(t):
                        edge = id(fut)
                        if edge not in seen_edge and edge in by_id:
                            seen_edge.add(edge)
                            awaiting_ids.append(edge)
                    else:
                        nested = _safe(lambda e=entry: list(e.awaited_by), [])
                        pending.extend(nested)
            awaiting_hex = ["0x{:x}".format(x) for x in awaiting_ids]
            tid_hex = "0x{:x}".format(id(t))
            for nid in awaiting_ids:
                awaited_by.setdefault(nid, []).append(id(t))
            out.append({
                "id": tid_hex,
                "name": _safe(t.get_name, "") or "",
                "state": _state(t),
                "coroutine": _coro_label(coro),
                "path": top.get("path"),
                "line": top.get("line"),
                "stack": stack,
                "awaiting": awaiting_hex,
                "awaited_by": [],
                "exception": _exception(t),
                "done": bool(_safe(t.done, False)),
                "cancelled": bool(_safe(t.cancelled, False)),
            })
        by_hex = {entry["id"]: entry for entry in out}
        for tid, parents in awaited_by.items():
            hex_id = "0x{:x}".format(tid)
            if hex_id in by_hex:
                by_hex[hex_id]["awaited_by"] = ["0x{:x}".format(p) for p in parents]
        return {
            "status": "ok" if out else "empty",
            "tasks": out,
            "python": _safe(lambda: __import__("sys").version.split()[0], ""),
        }

    try:
        return json.dumps(_collect())
    except Exception:
        tb = traceback.format_exc()
        return json.dumps({"status": "error", "tasks": [], "message": tb})

__yathaavat_collect_async_tasks__()
"""


def parse_collector_payload(raw: str | bytes | None) -> dict[str, object]:
    """Parse the collector's JSON payload, returning an error dict on failure."""
    if raw is None:
        return {"status": "unavailable", "tasks": [], "message": "no collector response"}
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            return {"status": "error", "tasks": [], "message": "non-utf8 payload"}
    text = raw.strip()
    if not text:
        return {"status": "empty", "tasks": []}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        return {"status": "error", "tasks": [], "message": f"invalid JSON: {exc}"}
    if not isinstance(parsed, dict):
        return {"status": "error", "tasks": [], "message": "payload is not an object"}
    return parsed


def build_task_graph(
    payload: dict[str, object] | None,
    *,
    default_status: TaskCaptureStatus = TaskCaptureStatus.OK,
) -> TaskGraphInfo:
    """Normalize a parsed payload into a :class:`TaskGraphInfo`.

    Always returns a graph — never raises. Missing/invalid data degrades to
    an explicit ``TaskCaptureStatus`` with an explanatory ``message``.
    """
    if payload is None:
        return TaskGraphInfo(status=TaskCaptureStatus.UNAVAILABLE, message="no payload")

    raw_status = payload.get("status")
    explicit_status: TaskCaptureStatus | None = None
    if isinstance(raw_status, str):
        try:
            explicit_status = TaskCaptureStatus(raw_status)
        except ValueError:
            explicit_status = None

    message_raw = payload.get("message")
    message = message_raw if isinstance(message_raw, str) and message_raw else None

    raw_tasks = payload.get("tasks")
    tasks: list[TaskInfo] = []
    partial = False
    if isinstance(raw_tasks, list):
        for entry in raw_tasks:
            info = _parse_task_entry(entry)
            if info is None:
                partial = True
                continue
            tasks.append(info)
    elif raw_tasks is not None:
        partial = True

    tasks_tuple = _order_tasks(tasks)

    # Normalize awaited_by from awaiting edges if the collector omitted it.
    tasks_tuple = _reconcile_await_edges(tasks_tuple)

    roots, cycles = _build_tree(tasks_tuple)

    status: TaskCaptureStatus
    if explicit_status is not None and explicit_status is not TaskCaptureStatus.OK:
        status = explicit_status
    elif not tasks_tuple:
        status = TaskCaptureStatus.EMPTY
    elif partial:
        status = TaskCaptureStatus.PARTIAL
    elif explicit_status is not None:
        status = explicit_status
    else:
        status = default_status

    return TaskGraphInfo(
        tasks=tasks_tuple,
        roots=tuple(roots),
        status=status,
        message=message,
        cycles=tuple(cycles),
    )


def _parse_task_entry(entry: object) -> TaskInfo | None:
    if not isinstance(entry, dict):
        return None
    tid = entry.get("id")
    if not isinstance(tid, str) or not tid:
        return None
    name_raw = entry.get("name")
    name = name_raw if isinstance(name_raw, str) and name_raw else tid

    state_raw = entry.get("state")
    try:
        state = TaskState(state_raw) if isinstance(state_raw, str) else TaskState.PENDING
    except ValueError:
        state = TaskState.PENDING

    coroutine_raw = entry.get("coroutine")
    coroutine = coroutine_raw if isinstance(coroutine_raw, str) else ""

    path_raw = entry.get("path")
    path = path_raw if isinstance(path_raw, str) and path_raw else None

    line_raw = entry.get("line")
    line = int(line_raw) if isinstance(line_raw, int) else None

    stack_raw = entry.get("stack")
    stack: list[TaskStackFrame] = []
    if isinstance(stack_raw, list):
        for frame_entry in stack_raw:
            frame = _parse_stack_frame(frame_entry)
            if frame is not None:
                stack.append(frame)

    awaiting = _parse_str_tuple(entry.get("awaiting"))
    awaited_by = _parse_str_tuple(entry.get("awaited_by"))

    exception_raw = entry.get("exception")
    exception = exception_raw if isinstance(exception_raw, str) and exception_raw else None

    done = bool(entry.get("done")) or state in {TaskState.DONE, TaskState.FAILED}
    cancelled = bool(entry.get("cancelled")) or state is TaskState.CANCELLED

    return TaskInfo(
        id=tid,
        name=name,
        state=state,
        coroutine=coroutine,
        path=path,
        line=line,
        stack=tuple(stack),
        awaiting=awaiting,
        awaited_by=awaited_by,
        exception=exception,
        done=done,
        cancelled=cancelled,
    )


def _parse_stack_frame(entry: object) -> TaskStackFrame | None:
    if not isinstance(entry, dict):
        return None
    name_raw = entry.get("name")
    name = name_raw if isinstance(name_raw, str) else ""
    path_raw = entry.get("path")
    path = path_raw if isinstance(path_raw, str) and path_raw else None
    line_raw = entry.get("line")
    line = int(line_raw) if isinstance(line_raw, int) else None
    return TaskStackFrame(name=name, path=path, line=line)


def _parse_str_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        if isinstance(item, str) and item and item not in seen:
            seen.add(item)
            out.append(item)
    return tuple(out)


def _order_tasks(tasks: list[TaskInfo]) -> tuple[TaskInfo, ...]:
    def sort_key(t: TaskInfo) -> tuple[int, str, str]:
        # Pending tasks first (most useful when debugging), then done/cancelled/failed.
        state_order = {
            TaskState.PENDING: 0,
            TaskState.CANCELLED: 1,
            TaskState.FAILED: 2,
            TaskState.DONE: 3,
        }.get(t.state, 4)
        return state_order, t.name.casefold(), t.id

    return tuple(sorted(tasks, key=sort_key))


def _reconcile_await_edges(tasks: tuple[TaskInfo, ...]) -> tuple[TaskInfo, ...]:
    ids = {t.id for t in tasks}
    derived: dict[str, list[str]] = {t.id: [] for t in tasks}
    for task in tasks:
        for child_id in task.awaiting:
            if child_id in ids and task.id not in derived[child_id]:
                derived[child_id].append(task.id)

    reconciled: list[TaskInfo] = []
    for task in tasks:
        # Filter awaiting/awaited_by to known tasks only so UI stays coherent.
        awaiting = tuple(tid for tid in task.awaiting if tid in ids)
        existing_awaited_by = tuple(tid for tid in task.awaited_by if tid in ids)
        merged_awaited_by = existing_awaited_by
        if not merged_awaited_by:
            merged_awaited_by = tuple(derived[task.id])
        reconciled.append(
            TaskInfo(
                id=task.id,
                name=task.name,
                state=task.state,
                coroutine=task.coroutine,
                path=task.path,
                line=task.line,
                stack=task.stack,
                awaiting=awaiting,
                awaited_by=merged_awaited_by,
                exception=task.exception,
                done=task.done,
                cancelled=task.cancelled,
            )
        )
    return tuple(reconciled)


def _build_tree(
    tasks: tuple[TaskInfo, ...],
) -> tuple[list[TaskNode], list[tuple[str, ...]]]:
    if not tasks:
        return [], []

    by_id = {t.id: t for t in tasks}
    cycles: list[tuple[str, ...]] = []
    seen_cycle_keys: set[frozenset[str]] = set()

    def expand(tid: str, ancestors: tuple[str, ...]) -> TaskNode:
        if tid in ancestors:
            cycle = (*ancestors[ancestors.index(tid) :], tid)
            key = frozenset(cycle)
            if key not in seen_cycle_keys:
                seen_cycle_keys.add(key)
                cycles.append(cycle)
            return TaskNode(task_id=tid, children=(), cycle_to=tid)
        task = by_id.get(tid)
        if task is None:
            return TaskNode(task_id=tid, children=())
        children = tuple(
            expand(child_id, (*ancestors, tid)) for child_id in task.awaiting if child_id in by_id
        )
        return TaskNode(task_id=tid, children=children)

    root_ids = [t.id for t in tasks if not t.awaited_by]
    if not root_ids:
        # Everything is in a cycle; pick a deterministic entry point per cluster.
        visited: set[str] = set()
        for task in tasks:
            if task.id in visited:
                continue
            cluster_id = task.id
            root_ids.append(cluster_id)
            stack = [cluster_id]
            while stack:
                node = stack.pop()
                if node in visited:
                    continue
                visited.add(node)
                node_task = by_id.get(node)
                if node_task is None:
                    continue
                stack.extend(node_task.awaiting)

    roots = [expand(tid, ()) for tid in root_ids]
    return roots, cycles


def find_task(graph: TaskGraphInfo | None, task_id: str | None) -> TaskInfo | None:
    if graph is None or task_id is None:
        return None
    for task in graph.tasks:
        if task.id == task_id:
            return task
    return None


def task_top_location(task: TaskInfo) -> tuple[str | None, int | None]:
    if task.path is not None:
        return task.path, task.line
    for frame in task.stack:
        if frame.path is not None:
            return frame.path, frame.line
    return None, None


def format_state_marker(task: TaskInfo) -> str:
    match task.state:
        case TaskState.PENDING:
            return "●"
        case TaskState.DONE:
            return "✓"
        case TaskState.CANCELLED:
            return "⊘"
        case TaskState.FAILED:
            return "✗"


def format_coroutine_label(task: TaskInfo, *, max_len: int = 48) -> str:
    label = task.coroutine or task.name or task.id
    if len(label) <= max_len:
        return label
    return label[: max(1, max_len - 1)] + "…"


def format_location(task: TaskInfo, *, max_len: int = 36) -> str:
    path, line = task_top_location(task)
    if path is None:
        return "—"
    basename = Path(path).name
    loc = f"{basename}:{line}" if line else basename
    if len(loc) <= max_len:
        return loc
    return loc[: max(1, max_len - 1)] + "…"


def format_awaiting_summary(task: TaskInfo, graph: TaskGraphInfo, *, max_len: int = 36) -> str:
    if not task.awaiting:
        return "—"
    by_id = {t.id: t for t in graph.tasks}
    names: list[str] = []
    for tid in task.awaiting:
        child = by_id.get(tid)
        if child is None:
            names.append(tid)
        else:
            names.append(child.name or tid)
    summary = ", ".join(names)
    if len(summary) <= max_len:
        return summary
    return summary[: max(1, max_len - 1)] + "…"
