from __future__ import annotations

from yathaavat.core.session import (
    BreakMode,
    ExceptionNode,
    ExceptionRelation,
    SessionSnapshot,
    SessionState,
    SessionStore,
    TracebackFrame,
)
from yathaavat.core.traceback_parser import build_exception_tree


def test_exception_info_on_snapshot() -> None:
    """ExceptionInfo can be stored on and retrieved from SessionSnapshot."""
    info = build_exception_tree(
        exception_id="ValueError",
        description="bad value",
        break_mode=BreakMode.UNHANDLED,
        stack_trace='Traceback:\n  File "a.py", line 1, in f\nValueError: bad value',
    )
    snap = SessionSnapshot(
        state=SessionState.PAUSED,
        stop_reason="exception",
        stop_description="ValueError: bad value",
        exception_info=info,
    )
    assert snap.exception_info is not None
    assert snap.exception_info.exception_id == "ValueError"
    assert snap.exception_info.tree.type_name == "ValueError"
    assert snap.exception_info.break_mode == BreakMode.UNHANDLED


def test_exception_info_default_none() -> None:
    """SessionSnapshot defaults exception_info to None."""
    snap = SessionSnapshot()
    assert snap.exception_info is None


def test_exception_info_store_update() -> None:
    """SessionStore.update() can set and clear exception_info."""
    store = SessionStore()
    assert store.snapshot().exception_info is None

    info = build_exception_tree(
        exception_id="RuntimeError",
        description="boom",
        break_mode=BreakMode.ALWAYS,
        stack_trace="",
    )
    store.update(exception_info=info)
    exc = store.snapshot().exception_info
    assert exc is not None
    assert exc.exception_id == "RuntimeError"

    store.update(exception_info=None)
    assert store.snapshot().exception_info is None


def test_exception_info_listener_notified() -> None:
    """Store listeners are notified when exception_info changes."""
    store = SessionStore()
    snapshots: list[SessionSnapshot] = []
    store.subscribe(lambda s: snapshots.append(s), emit_current=False)

    info = build_exception_tree(
        exception_id="TypeError",
        description="wrong type",
        break_mode=BreakMode.UNHANDLED,
        stack_trace="",
    )
    store.update(exception_info=info)
    assert len(snapshots) == 1
    assert snapshots[0].exception_info is not None

    store.update(exception_info=None)
    assert len(snapshots) == 2
    assert snapshots[1].exception_info is None


def test_exception_node_relation_types() -> None:
    """ExceptionNode relation types are correctly assigned."""
    root = ExceptionNode(
        type_name="RuntimeError",
        message="failed",
        relation=ExceptionRelation.ROOT,
        children=(
            ExceptionNode(
                type_name="ConnectionError",
                message="db timeout",
                relation=ExceptionRelation.CAUSE,
            ),
        ),
    )
    assert root.relation == ExceptionRelation.ROOT
    assert root.children[0].relation == ExceptionRelation.CAUSE


def test_exception_node_group_member() -> None:
    """ExceptionGroup children have GROUP_MEMBER relation."""
    group = ExceptionNode(
        type_name="ExceptionGroup",
        message="multi (2 sub-exceptions)",
        is_group=True,
        children=(
            ExceptionNode(
                type_name="ValueError",
                message="bad",
                relation=ExceptionRelation.GROUP_MEMBER,
            ),
            ExceptionNode(
                type_name="TypeError",
                message="wrong",
                relation=ExceptionRelation.GROUP_MEMBER,
            ),
        ),
    )
    assert group.is_group is True
    assert all(c.relation == ExceptionRelation.GROUP_MEMBER for c in group.children)


def test_traceback_frame_fields() -> None:
    """TracebackFrame stores path, line, name, and optional text."""
    frame = TracebackFrame(path="app/main.py", line=42, name="main", text="print('hello')")
    assert frame.path == "app/main.py"
    assert frame.line == 42
    assert frame.name == "main"
    assert frame.text == "print('hello')"

    frame_no_text = TracebackFrame(path=None, line=None, name="<module>")
    assert frame_no_text.path is None
    assert frame_no_text.text is None
