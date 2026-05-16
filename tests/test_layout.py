from __future__ import annotations

from textual.widgets import Static

from yathaavat.app.layout import _safe_dom_id
from yathaavat.core import WidgetContribution
from yathaavat.core.widgets import Slot


def test_safe_dom_id_replaces_non_alphanumeric_chars() -> None:
    contribution = WidgetContribution(
        id="plugin.source/find",
        title="Find",
        slot=Slot.CENTER,
        factory=lambda _ctx: Static("x"),
    )
    assert _safe_dom_id(contribution) == "pane_plugin_source_find"
