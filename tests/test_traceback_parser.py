from __future__ import annotations

from yathaavat.core.session import BreakMode, ExceptionRelation
from yathaavat.core.traceback_parser import build_exception_tree, parse_traceback_frames

_SIMPLE_TRACEBACK = """\
Traceback (most recent call last):
  File "app/service.py", line 42, in process_order
    total = int(order.amount)
  File "app/handlers.py", line 18, in handle_request
    return process(data)
ValueError: invalid literal for int() with base 10: 'abc'
"""

_CHAINED_CAUSE = """\
Traceback (most recent call last):
  File "db/pool.py", line 88, in acquire
    conn = pool.get()
ConnectionError: db timeout

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "app/service.py", line 28, in process_order
    result = fetch_data()
RuntimeError: failed to process order
"""

_CHAINED_CONTEXT = """\
Traceback (most recent call last):
  File "app/main.py", line 10, in run
    data[key]
KeyError: 'missing_key'

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "app/main.py", line 12, in run
    raise TypeError("wrong type")
TypeError: wrong type
"""

_EXCEPTION_GROUP_FLAT = """\
  + Exception Group Traceback (most recent call last):
  |   File "app/main.py", line 5, in main
  |     raise ExceptionGroup("multiple failures", errors)
  | ExceptionGroup: multiple failures (2 sub-exceptions)
  +-+---------------- 1 ----------------
    | ValueError: invalid amount
    +---------------- 2 ----------------
    | ConnectionError: db timeout
    +------------------------------------
"""

_EXCEPTION_GROUP_NESTED = """\
  + Exception Group Traceback (most recent call last):
  |   File "app/main.py", line 10, in main
  |     raise ExceptionGroup("outer", errors)
  | ExceptionGroup: outer (2 sub-exceptions)
  +-+---------------- 1 ----------------
    | ValueError: bad value
    +---------------- 2 ----------------
    | ExceptionGroup: inner (2 sub-exceptions)
    +-+---------------- 1 ----------------
      | TypeError: wrong type
      +---------------- 2 ----------------
      | OSError: disk full
      +------------------------------------
"""


def test_parse_traceback_frames_simple() -> None:
    frames = parse_traceback_frames(_SIMPLE_TRACEBACK)
    assert len(frames) == 2
    assert frames[0].path == "app/service.py"
    assert frames[0].line == 42
    assert frames[0].name == "process_order"
    assert frames[0].text == "total = int(order.amount)"
    assert frames[1].path == "app/handlers.py"
    assert frames[1].line == 18
    assert frames[1].name == "handle_request"


def test_parse_traceback_frames_empty() -> None:
    frames = parse_traceback_frames("")
    assert frames == ()


def test_parse_traceback_frames_no_match() -> None:
    frames = parse_traceback_frames("some random garbage text\nno frames here")
    assert frames == ()


def test_parse_traceback_frames_with_source_text() -> None:
    frames = parse_traceback_frames(_SIMPLE_TRACEBACK)
    assert frames[0].text == "total = int(order.amount)"
    assert frames[1].text == "return process(data)"


def test_build_tree_simple_exception() -> None:
    info = build_exception_tree(
        exception_id="ValueError",
        description="bad value",
        break_mode=BreakMode.UNHANDLED,
        stack_trace=_SIMPLE_TRACEBACK,
    )
    assert info.exception_id == "ValueError"
    assert info.break_mode == BreakMode.UNHANDLED
    assert info.tree.type_name == "ValueError"
    assert info.tree.message == "invalid literal for int() with base 10: 'abc'"
    assert len(info.tree.frames) == 2
    assert info.tree.children == ()
    assert info.tree.relation == ExceptionRelation.ROOT


def test_build_tree_chained_cause() -> None:
    info = build_exception_tree(
        exception_id="RuntimeError",
        description="failed to process order",
        break_mode=BreakMode.ALWAYS,
        stack_trace=_CHAINED_CAUSE,
    )
    tree = info.tree
    assert tree.type_name == "RuntimeError"
    assert tree.relation == ExceptionRelation.ROOT
    assert len(tree.frames) == 1
    assert len(tree.children) == 1
    cause = tree.children[0]
    assert cause.type_name == "ConnectionError"
    assert cause.relation == ExceptionRelation.CAUSE
    assert len(cause.frames) == 1


def test_build_tree_chained_context() -> None:
    info = build_exception_tree(
        exception_id="TypeError",
        description="wrong type",
        break_mode=BreakMode.UNHANDLED,
        stack_trace=_CHAINED_CONTEXT,
    )
    tree = info.tree
    assert tree.type_name == "TypeError"
    assert tree.relation == ExceptionRelation.ROOT
    assert len(tree.children) == 1
    ctx = tree.children[0]
    assert ctx.type_name == "KeyError"
    assert ctx.relation == ExceptionRelation.CONTEXT


_MIXED_CHAIN = """\
Traceback (most recent call last):
  File "db/pool.py", line 5, in connect
    raise ConnectionError("db timeout")
ConnectionError: db timeout

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "app/service.py", line 10, in fetch
    raise IOError("fetch failed")
IOError: fetch failed

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "app/main.py", line 3, in run
    raise RuntimeError("total failure") from e
RuntimeError: total failure
"""


def test_build_tree_mixed_chain() -> None:
    """Traceback with both __context__ and __cause__ markers."""
    info = build_exception_tree(
        exception_id="RuntimeError",
        description="total failure",
        break_mode=BreakMode.UNHANDLED,
        stack_trace=_MIXED_CHAIN,
    )
    tree = info.tree
    assert tree.type_name == "RuntimeError"
    assert tree.relation == ExceptionRelation.ROOT
    # Properly nested: RuntimeError → IOError(cause) → ConnectionError(context)
    assert len(tree.children) == 1
    cause = tree.children[0]
    assert cause.type_name == "IOError"
    assert cause.relation == ExceptionRelation.CAUSE
    assert len(cause.children) == 1
    ctx = cause.children[0]
    assert ctx.type_name == "ConnectionError"
    assert ctx.relation == ExceptionRelation.CONTEXT


def test_build_tree_exception_group_flat() -> None:
    info = build_exception_tree(
        exception_id="ExceptionGroup",
        description="multiple failures (2 sub-exceptions)",
        break_mode=BreakMode.ALWAYS,
        stack_trace=_EXCEPTION_GROUP_FLAT,
    )
    tree = info.tree
    assert tree.is_group is True
    assert tree.type_name == "ExceptionGroup"
    assert len(tree.children) == 2
    assert tree.children[0].type_name == "ValueError"
    assert tree.children[0].relation == ExceptionRelation.GROUP_MEMBER
    assert tree.children[1].type_name == "ConnectionError"
    assert tree.children[1].relation == ExceptionRelation.GROUP_MEMBER


def test_build_tree_exception_group_nested() -> None:
    info = build_exception_tree(
        exception_id="ExceptionGroup",
        description="outer (2 sub-exceptions)",
        break_mode=BreakMode.ALWAYS,
        stack_trace=_EXCEPTION_GROUP_NESTED,
    )
    tree = info.tree
    assert tree.is_group is True
    assert len(tree.children) == 2
    assert tree.children[0].type_name == "ValueError"
    inner = tree.children[1]
    assert inner.is_group is True
    assert inner.type_name == "ExceptionGroup"
    assert len(inner.children) == 2
    assert inner.children[0].type_name == "TypeError"
    assert inner.children[1].type_name == "OSError"


def test_build_tree_malformed_input() -> None:
    info = build_exception_tree(
        exception_id="SomeError",
        description="something went wrong",
        break_mode=BreakMode.NEVER,
        stack_trace="completely unparseable garbage \x00\x01\x02",
    )
    assert info.tree.type_name == "SomeError"
    assert info.tree.message == "something went wrong"
    assert info.tree.frames == ()


def test_build_tree_empty_stack_trace() -> None:
    info = build_exception_tree(
        exception_id="RuntimeError",
        description="no trace",
        break_mode=BreakMode.UNHANDLED,
        stack_trace="",
    )
    assert info.tree.type_name == "RuntimeError"
    assert info.tree.message == "no trace"
    assert info.tree.frames == ()


def test_build_tree_break_mode_preserved() -> None:
    for mode in BreakMode:
        info = build_exception_tree(
            exception_id="X",
            description="",
            break_mode=mode,
            stack_trace="",
        )
        assert info.break_mode == mode
