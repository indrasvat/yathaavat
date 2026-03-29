from __future__ import annotations

from dataclasses import dataclass

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Static, TabbedContent, TabPane

from yathaavat.core import AppContext, Slot, WidgetContribution


@dataclass(frozen=True, slots=True)
class SlotDescriptor:
    slot: Slot
    fallback_title: str


class SlotTabs(Container):
    def __init__(self, *, ctx: AppContext, slot: SlotDescriptor, id: str) -> None:
        super().__init__(id=id, classes="pane")
        self._ctx = ctx
        self._slot = slot

    def compose(self) -> ComposeResult:
        contributions = self._ctx.widgets.contributions_for(self._slot.slot)
        if not contributions:
            yield Static(
                f"{self._slot.fallback_title}\n\n(no panels registered)",
                classes="pane_empty",
            )
            return

        with TabbedContent():
            for contribution in contributions:
                with TabPane(contribution.title, id=_safe_dom_id(contribution)):
                    yield contribution.factory(self._ctx)


def _safe_dom_id(contribution: WidgetContribution) -> str:
    return "pane_" + "".join(ch if ch.isalnum() else "_" for ch in contribution.id)
