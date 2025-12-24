from __future__ import annotations

from dataclasses import dataclass

from yathaavat.app.panels import BreakpointsTable
from yathaavat.core import (
    SESSION_STORE,
    AppContext,
    BreakpointInfo,
    CommandRegistry,
    NullUiHost,
    ServiceRegistry,
    SessionStore,
    WidgetRegistry,
)


@dataclass(frozen=True, slots=True)
class _RowHighlighted:
    cursor_row: int


def test_breakpoints_table_does_not_jump_source_when_unfocused() -> None:
    services = ServiceRegistry()
    store = SessionStore()
    services.register(SESSION_STORE, store)

    ctx = AppContext(
        commands=CommandRegistry(),
        widgets=WidgetRegistry(),
        services=services,
        host=NullUiHost(),
    )

    table = BreakpointsTable(ctx=ctx, store=store)
    table.set_breakpoints((BreakpointInfo(path="/tmp/example.py", line=12, verified=None),))

    assert store.snapshot().source_path is None
    table._on_row_highlighted(_RowHighlighted(cursor_row=0))  # type: ignore[arg-type]
    assert store.snapshot().source_path is None
