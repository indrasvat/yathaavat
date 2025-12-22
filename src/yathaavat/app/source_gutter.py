from __future__ import annotations

from dataclasses import dataclass

from rich.segment import Segment
from rich.style import Style
from textual.strip import Strip

from yathaavat.core import BreakpointInfo


@dataclass(frozen=True, slots=True)
class GutterMarker:
    symbol: str
    style: Style


_BP_VERIFIED = GutterMarker("●", Style(color="#ff5c5c"))
_BP_QUEUED = GutterMarker("◌", Style(color="#f2c94c"))
_BP_PENDING = GutterMarker("◌", Style(color="#8bd5ff", dim=True))
_BP_FAILED = GutterMarker("✗", Style(color="#ff5c5c"))
EXEC_MARKER = GutterMarker("▶", Style(color="#4ade80", bold=True))


def marker_for_breakpoint(bp: BreakpointInfo) -> GutterMarker:
    if bp.verified is True:
        return _BP_VERIFIED
    if bp.verified is False:
        return _BP_FAILED
    if (bp.message or "").strip().lower() == "queued":
        return _BP_QUEUED
    return _BP_PENDING


def apply_gutter_marker(strip: Strip, *, gutter_width: int, marker: GutterMarker) -> Strip:
    """Overlay a breakpoint marker into a TextArea line-number gutter.

    Textual's TextArea gutter uses the last two cells as margin ("  "). We replace those
    two cells with "<marker><space>" so the code column does not shift.
    """

    if gutter_width < 2:
        return strip

    cell_length = strip.cell_length
    if gutter_width >= cell_length:
        return strip

    parts = strip.divide([gutter_width, cell_length])
    if len(parts) != 2:
        return strip

    gutter, rest = parts
    prefix = gutter.crop(0, gutter_width - 2)
    marker_strip = Strip([Segment(f"{marker.symbol} ", marker.style)], cell_length=2)
    return Strip.join([Strip.join([prefix, marker_strip]), rest])
