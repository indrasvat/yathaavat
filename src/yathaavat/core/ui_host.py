from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from textual.screen import Screen


@runtime_checkable
class UiHost(Protocol):
    def notify(self, message: str, *, timeout: float = 1.2) -> None: ...

    def exit(self) -> None: ...

    def push_screen(self, screen: Screen[Any]) -> None: ...

    def pop_screen(self) -> None: ...


@dataclass(frozen=True, slots=True)
class NullUiHost(UiHost):
    def notify(self, message: str, *, timeout: float = 1.2) -> None:
        return

    def exit(self) -> None:
        return

    def push_screen(self, screen: Screen[Any]) -> None:
        return

    def pop_screen(self) -> None:
        return
