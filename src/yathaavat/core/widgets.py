from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from textual.widget import Widget

    from yathaavat.core.app_context import AppContext


class Slot(StrEnum):
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"
    BOTTOM_LEFT = "bottom_left"
    BOTTOM_RIGHT = "bottom_right"


if TYPE_CHECKING:
    type WidgetFactory = Callable[[AppContext], Widget]
else:
    type WidgetFactory = Callable[..., object]


@dataclass(frozen=True, slots=True)
class WidgetContribution:
    id: str
    title: str
    slot: Slot
    factory: WidgetFactory
    order: int = 0


class WidgetRegistry:
    def __init__(self) -> None:
        self._by_slot: dict[Slot, list[WidgetContribution]] = {slot: [] for slot in Slot}
        self._by_id: dict[str, WidgetContribution] = {}

    def register(self, contribution: WidgetContribution) -> None:
        if contribution.id in self._by_id:
            msg = f"Widget already registered: {contribution.id}"
            raise ValueError(msg)
        self._by_slot[contribution.slot].append(contribution)
        self._by_id[contribution.id] = contribution

    def get(self, widget_id: str) -> WidgetContribution:
        try:
            return self._by_id[widget_id]
        except KeyError as exc:
            raise KeyError(f"Unknown widget: {widget_id}") from exc

    def contributions_for(self, slot: Slot) -> tuple[WidgetContribution, ...]:
        return tuple(sorted(self._by_slot[slot], key=lambda c: (c.order, c.title, c.id)))
