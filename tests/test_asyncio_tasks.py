from __future__ import annotations

import json

from yathaavat.core.asyncio_tasks import (
    TASK_COLLECTOR_CALL,
    TASK_COLLECTOR_DEFINE,
    TASK_COLLECTOR_SOURCE,
    build_task_graph,
    find_task,
    format_awaiting_summary,
    format_coroutine_label,
    format_location,
    format_state_marker,
    format_task_detail,
    parse_collector_payload,
    task_top_location,
    unwrap_evaluate_repr,
)
from yathaavat.core.session import (
    TaskCaptureStatus,
    TaskInfo,
    TaskState,
)


def _payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {"status": "ok", "tasks": []}
    base.update(overrides)
    return base


def _task_entry(
    tid: str,
    *,
    name: str | None = None,
    state: str = "pending",
    coroutine: str = "worker",
    path: str | None = "/app/main.py",
    line: int | None = 42,
    stack: list[dict[str, object]] | None = None,
    awaiting: list[str] | None = None,
    awaited_by: list[str] | None = None,
    exception: str | None = None,
    done: bool = False,
    cancelled: bool = False,
) -> dict[str, object]:
    return {
        "id": tid,
        "name": name if name is not None else tid,
        "state": state,
        "coroutine": coroutine,
        "path": path,
        "line": line,
        "stack": stack or [{"name": "run", "path": path, "line": line}],
        "awaiting": awaiting or [],
        "awaited_by": awaited_by or [],
        "exception": exception,
        "done": done,
        "cancelled": cancelled,
    }


def test_parse_collector_payload_returns_unavailable_for_none() -> None:
    result = parse_collector_payload(None)
    assert result["status"] == "unavailable"
    assert result["tasks"] == []


def test_parse_collector_payload_decodes_bytes() -> None:
    raw = json.dumps({"status": "ok", "tasks": []}).encode("utf-8")
    result = parse_collector_payload(raw)
    assert result["status"] == "ok"


def test_parse_collector_payload_returns_empty_for_blank_string() -> None:
    result = parse_collector_payload("   ")
    assert result["status"] == "empty"


def test_parse_collector_payload_returns_error_for_invalid_json() -> None:
    result = parse_collector_payload("{not-json}")
    assert result["status"] == "error"
    assert "invalid JSON" in str(result["message"])


def test_parse_collector_payload_rejects_non_object() -> None:
    result = parse_collector_payload("[1,2,3]")
    assert result["status"] == "error"


def test_build_task_graph_empty_payload_status_is_empty() -> None:
    graph = build_task_graph(_payload(status="ok", tasks=[]))
    assert graph.status == TaskCaptureStatus.EMPTY
    assert graph.tasks == ()
    assert graph.roots == ()


def test_build_task_graph_none_payload_is_unavailable() -> None:
    graph = build_task_graph(None)
    assert graph.status == TaskCaptureStatus.UNAVAILABLE


def test_build_task_graph_single_task_creates_root() -> None:
    graph = build_task_graph(_payload(tasks=[_task_entry("0x1", name="worker")]))
    assert graph.status == TaskCaptureStatus.OK
    assert len(graph.tasks) == 1
    task = graph.tasks[0]
    assert task.id == "0x1"
    assert task.name == "worker"
    assert task.state == TaskState.PENDING
    assert len(graph.roots) == 1
    assert graph.roots[0].task_id == "0x1"
    assert graph.roots[0].children == ()


def test_build_task_graph_parent_awaits_child_tree() -> None:
    payload = _payload(
        tasks=[
            _task_entry("0xp", name="parent", awaiting=["0xc"]),
            _task_entry("0xc", name="child", awaited_by=["0xp"]),
        ]
    )
    graph = build_task_graph(payload)
    assert len(graph.roots) == 1
    root = graph.roots[0]
    assert root.task_id == "0xp"
    assert len(root.children) == 1
    assert root.children[0].task_id == "0xc"


def test_build_task_graph_derives_awaited_by_from_awaiting_when_missing() -> None:
    payload = _payload(
        tasks=[
            _task_entry("0xp", name="parent", awaiting=["0xc"]),
            _task_entry("0xc", name="child", awaited_by=[]),
        ]
    )
    graph = build_task_graph(payload)
    child = next(t for t in graph.tasks if t.id == "0xc")
    assert "0xp" in child.awaited_by
    assert len(graph.roots) == 1
    assert graph.roots[0].task_id == "0xp"


def test_build_task_graph_detects_cycle() -> None:
    payload = _payload(
        tasks=[
            _task_entry("0xa", name="a", awaiting=["0xb"], awaited_by=["0xb"]),
            _task_entry("0xb", name="b", awaiting=["0xa"], awaited_by=["0xa"]),
        ]
    )
    graph = build_task_graph(payload)
    assert graph.cycles
    assert graph.roots, "expected at least one synthesized root for cycle cluster"

    def any_cycle_marker(nodes: object) -> bool:
        stack = list(nodes) if isinstance(nodes, tuple | list) else []
        while stack:
            node = stack.pop()
            if getattr(node, "cycle_to", None) is not None:
                return True
            stack.extend(getattr(node, "children", ()))
        return False

    assert any_cycle_marker(graph.roots)


def test_build_task_graph_filters_unknown_awaiting_ids() -> None:
    payload = _payload(
        tasks=[_task_entry("0x1", name="worker", awaiting=["0xdead"])],
    )
    graph = build_task_graph(payload)
    task = graph.tasks[0]
    assert task.awaiting == ()


def test_build_task_graph_partial_when_entries_are_invalid() -> None:
    payload = _payload(tasks=[_task_entry("0x1"), "bad-entry"])
    graph = build_task_graph(payload)
    assert graph.status == TaskCaptureStatus.PARTIAL
    assert len(graph.tasks) == 1


def test_build_task_graph_deterministic_order() -> None:
    payload = _payload(
        tasks=[
            _task_entry("0x3", name="beta", state="pending"),
            _task_entry("0x1", name="alpha", state="done", done=True),
            _task_entry("0x2", name="alpha", state="pending"),
        ]
    )
    graph = build_task_graph(payload)
    ordered = [(t.state.value, t.name, t.id) for t in graph.tasks]
    assert ordered == [
        ("pending", "alpha", "0x2"),
        ("pending", "beta", "0x3"),
        ("done", "alpha", "0x1"),
    ]


def test_build_task_graph_honors_explicit_status() -> None:
    graph = build_task_graph(_payload(status="unsupported", message="no asyncio"))
    assert graph.status == TaskCaptureStatus.UNSUPPORTED
    assert graph.message == "no asyncio"


def test_build_task_graph_cancelled_and_failed_flags() -> None:
    payload = _payload(
        tasks=[
            _task_entry(
                "0x1",
                name="cancelled",
                state="cancelled",
                cancelled=True,
                done=True,
            ),
            _task_entry(
                "0x2",
                name="failed",
                state="failed",
                exception="ValueError: bad input",
                done=True,
            ),
        ]
    )
    graph = build_task_graph(payload)
    cancelled = next(t for t in graph.tasks if t.id == "0x1")
    failed = next(t for t in graph.tasks if t.id == "0x2")
    assert cancelled.state == TaskState.CANCELLED
    assert cancelled.cancelled is True
    assert cancelled.done is True
    assert failed.state == TaskState.FAILED
    assert failed.done is True
    assert failed.exception == "ValueError: bad input"


def test_find_task_returns_match_and_none() -> None:
    graph = build_task_graph(_payload(tasks=[_task_entry("0xa", name="a")]))
    assert find_task(graph, "0xa") is not None
    assert find_task(graph, "0xmissing") is None
    assert find_task(None, "0xa") is None


def test_task_top_location_prefers_explicit_then_stack() -> None:
    graph = build_task_graph(
        _payload(
            tasks=[
                _task_entry(
                    "0x1",
                    name="explicit",
                    path="/a.py",
                    line=10,
                    stack=[{"name": "run", "path": "/b.py", "line": 20}],
                ),
                _task_entry(
                    "0x2",
                    name="stack-only",
                    path=None,
                    line=None,
                    stack=[{"name": "run", "path": "/c.py", "line": 30}],
                ),
                _task_entry(
                    "0x3",
                    name="no-loc",
                    path=None,
                    line=None,
                    stack=[],
                ),
            ]
        )
    )
    by_id = {t.id: t for t in graph.tasks}
    assert task_top_location(by_id["0x1"]) == ("/a.py", 10)
    assert task_top_location(by_id["0x2"]) == ("/c.py", 30)
    assert task_top_location(by_id["0x3"]) == (None, None)


def test_format_state_marker_maps_each_state() -> None:
    def m(state: TaskState) -> str:
        return format_state_marker(TaskInfo(id="x", name="x", state=state, coroutine="c"))

    assert m(TaskState.PENDING) == "●"
    assert m(TaskState.DONE) == "✓"
    assert m(TaskState.CANCELLED) == "⊘"
    assert m(TaskState.FAILED) == "✗"


def test_format_coroutine_label_truncates() -> None:
    task = TaskInfo(
        id="0x1",
        name="t",
        state=TaskState.PENDING,
        coroutine="a" * 200,
    )
    assert format_coroutine_label(task, max_len=10).endswith("…")
    assert len(format_coroutine_label(task, max_len=10)) == 10


def test_format_location_handles_missing_and_long_paths() -> None:
    short = TaskInfo(
        id="0x1", name="t", state=TaskState.PENDING, coroutine="c", path="/a.py", line=5
    )
    assert format_location(short) == "a.py:5"

    missing = TaskInfo(id="0x2", name="t", state=TaskState.PENDING, coroutine="c")
    assert format_location(missing) == "—"

    long_name = "x" * 80 + ".py"
    long_path = TaskInfo(
        id="0x3",
        name="t",
        state=TaskState.PENDING,
        coroutine="c",
        path="/" + long_name,
        line=9,
    )
    result = format_location(long_path, max_len=12)
    assert result.endswith("…")
    assert len(result) == 12


def test_format_awaiting_summary_uses_child_names_and_truncates() -> None:
    payload = _payload(
        tasks=[
            _task_entry("0xp", name="parent", awaiting=["0xa", "0xb"]),
            _task_entry("0xa", name="first"),
            _task_entry("0xb", name="second"),
        ]
    )
    graph = build_task_graph(payload)
    parent = next(t for t in graph.tasks if t.id == "0xp")
    summary = format_awaiting_summary(parent, graph, max_len=100)
    assert summary == "first, second"

    lonely = next(t for t in graph.tasks if t.id == "0xa")
    assert format_awaiting_summary(lonely, graph) == "—"

    short = format_awaiting_summary(parent, graph, max_len=6)
    assert short.endswith("…")
    assert len(short) == 6


def test_format_task_detail_includes_relationships_and_stack() -> None:
    payload = _payload(
        tasks=[
            _task_entry(
                "0xp",
                name="parent",
                coroutine="run_parent",
                path="/app/parent.py",
                line=10,
                awaiting=["0xc"],
                stack=[
                    {"name": "main", "path": "/app/main.py", "line": 3},
                    {"name": "run_parent", "path": "/app/parent.py", "line": 10},
                ],
            ),
            _task_entry("0xc", name="child", awaited_by=["0xp"]),
        ]
    )
    graph = build_task_graph(payload)
    parent = next(t for t in graph.tasks if t.id == "0xp")

    detail = format_task_detail(parent, graph)

    assert "Task: parent (0xp) [pending]" in detail
    assert "Coroutine: run_parent" in detail
    assert "Location: parent.py:10" in detail
    assert "Awaiting: child" in detail
    assert "Awaited by: none" in detail
    assert "main @ main.py:3" in detail
    assert "run_parent @ parent.py:10" in detail


def test_format_task_detail_shows_failed_exception_and_stack_limit() -> None:
    payload = _payload(
        tasks=[
            _task_entry(
                "0xf",
                name="failed",
                state="failed",
                exception="RuntimeError: boom",
                done=True,
                stack=[
                    {"name": "a", "path": "/app/a.py", "line": 1},
                    {"name": "b", "path": "/app/b.py", "line": 2},
                    {"name": "c", "path": "/app/c.py", "line": 3},
                ],
            ),
        ]
    )
    graph = build_task_graph(payload)
    task = graph.tasks[0]

    detail = format_task_detail(task, graph, max_stack=2)

    assert "Task: failed (0xf) [failed]" in detail
    assert "Exception: RuntimeError: boom" in detail
    assert "a @ a.py:1" in detail
    assert "b @ b.py:2" in detail
    assert "c @ c.py:3" not in detail
    assert "... 1 more frame(s)" in detail


def test_unwrap_evaluate_repr_strips_single_quote_wrapping() -> None:
    # debugpy's repr for a JSON string that contains only double quotes uses
    # single quotes as the outer delimiter and does NOT escape the internals.
    wrapped = '\'{"status": "ok", "tasks": []}\''
    assert unwrap_evaluate_repr(wrapped) == '{"status": "ok", "tasks": []}'


def test_unwrap_evaluate_repr_strips_double_quote_wrapping_with_escapes() -> None:
    # When the value contains a single quote, repr picks double quotes and
    # escapes any internal double quotes.
    wrapped = '"{\\"status\\": \\"ok\\", \\"msg\\": \\"it\'s fine\\"}"'
    assert unwrap_evaluate_repr(wrapped) == '{"status": "ok", "msg": "it\'s fine"}'


def test_unwrap_evaluate_repr_noop_on_bare_json() -> None:
    bare = '{"status": "ok", "tasks": []}'
    assert unwrap_evaluate_repr(bare) == bare


def test_unwrap_evaluate_repr_handles_short_input() -> None:
    assert unwrap_evaluate_repr("") == ""
    assert unwrap_evaluate_repr("'") == "'"
    assert unwrap_evaluate_repr("''") == ""


def test_parse_collector_payload_handles_debugpy_repr_wrapping() -> None:
    wrapped = '\'{"status": "ok", "tasks": [], "python": "3.14.4"}\''
    payload = parse_collector_payload(wrapped)
    assert payload["status"] == "ok"
    assert payload["tasks"] == []
    assert payload["python"] == "3.14.4"


def test_task_collector_define_has_no_trailing_call() -> None:
    # The define block may mention the function via `def name():` but must
    # NOT end with a bare `name()` statement — debugpy's exec-mode evaluate
    # would otherwise discard the return value, yielding an empty result.
    assert TASK_COLLECTOR_CALL == "__yathaavat_collect_async_tasks__()"
    tail_lines = [
        line
        for line in TASK_COLLECTOR_DEFINE.splitlines()
        if line.strip() and not line.startswith((" ", "\t"))
    ]
    # Every top-level line in the define block should begin with `def ` — no
    # bare call statements at module/top scope.
    for line in tail_lines:
        assert line.startswith("def "), f"unexpected top-level stmt in define block: {line!r}"


def test_task_collector_source_is_define_plus_call() -> None:
    assert TASK_COLLECTOR_DEFINE in TASK_COLLECTOR_SOURCE
    assert TASK_COLLECTOR_CALL in TASK_COLLECTOR_SOURCE


def test_task_collector_runs_in_process_and_returns_json() -> None:
    # Running the full TASK_COLLECTOR_SOURCE in a fresh namespace exercises the
    # define + call as a unit without the DAP layer. It must produce a JSON
    # string that parses into the expected schema.
    ns: dict[str, object] = {}
    result = eval(
        compile(TASK_COLLECTOR_SOURCE, "<collector>", "exec"),
        ns,
        ns,
    )
    # exec-mode compile returns None; the function is now defined in ns and we
    # can call it explicitly to get the JSON payload.
    assert result is None
    fn = ns["__yathaavat_collect_async_tasks__"]
    assert callable(fn)
    text = fn()
    assert isinstance(text, str)
    parsed = json.loads(text)
    assert parsed["status"] in ("ok", "empty")
    assert isinstance(parsed["tasks"], list)


def test_task_collector_failed_task_location_points_at_exception_site() -> None:
    # Task.get_stack() returns oldest->newest traceback frames for failed tasks,
    # so the exception site is at stack[-1]. The collector must pick that frame
    # for the task's path/line to avoid jumping to the caller instead of the
    # raise site.
    import asyncio

    async def _inner_raises() -> None:  # line reported for the failure
        raise RuntimeError("boom")

    async def _outer() -> None:
        await _inner_raises()

    async def _run() -> str:
        task = asyncio.create_task(_outer(), name="failing")
        try:
            await task
        except RuntimeError:
            pass
        assert task.done()
        ns: dict[str, object] = {}
        exec(compile(TASK_COLLECTOR_SOURCE, "<collector>", "exec"), ns, ns)
        fn = ns["__yathaavat_collect_async_tasks__"]
        assert callable(fn)
        out = fn()
        assert isinstance(out, str)
        return out

    text = asyncio.run(_run())
    parsed = json.loads(text)
    assert parsed["status"] == "ok"
    failing = next((t for t in parsed["tasks"] if t.get("name") == "failing"), None)
    assert failing is not None, f"expected failing task in payload: {parsed}"
    assert failing["state"] == "failed"
    # stack is oldest->newest; the exception is raised in _inner_raises so the
    # newest frame must be selected for path/line.
    stack = failing["stack"]
    assert stack, "failed task should have a non-empty traceback stack"
    newest = stack[-1]
    assert newest["name"] == "_inner_raises"
    assert failing["path"] == newest["path"]
    assert failing["line"] == newest["line"]
