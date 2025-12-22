from __future__ import annotations

from rich.segment import Segment
from rich.style import Style
from textual.strip import Strip

from yathaavat.app.source_gutter import GutterMarker, apply_gutter_marker, marker_for_breakpoint
from yathaavat.core import BreakpointInfo


def test_marker_for_breakpoint_states() -> None:
    assert marker_for_breakpoint(BreakpointInfo(path="x", line=1, verified=True)).symbol == "●"
    assert marker_for_breakpoint(BreakpointInfo(path="x", line=1, verified=False)).symbol == "✗"
    assert (
        marker_for_breakpoint(
            BreakpointInfo(path="x", line=1, verified=None, message="queued")
        ).symbol
        == "◌"
    )
    assert marker_for_breakpoint(BreakpointInfo(path="x", line=1, verified=None)).symbol == "◌"


def test_apply_gutter_marker_replaces_last_two_cells() -> None:
    gutter_width = 6
    gutter = Strip([Segment("  12  ", Style(color="blue"))], cell_length=gutter_width)
    code = Strip([Segment("print('hi')", Style(color="white"))])
    line = Strip.join([gutter, code])

    marked = apply_gutter_marker(
        line,
        gutter_width=gutter_width,
        marker=GutterMarker("●", Style(color="red")),
    )
    assert marked.text.startswith("  12● ")
    assert "print('hi')" in marked.text
