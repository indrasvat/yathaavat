from __future__ import annotations

from dataclasses import dataclass
from typing import Self

from textual.app import App
from textual.screen import Screen

from yathaavat.core.ui_host import UiHost


@dataclass(slots=True)
class TextualUiHost(UiHost):
    _app: App[None] | None = None

    def bind(self, app: App[None]) -> Self:
        self._app = app
        return self

    def notify(self, message: str, *, timeout: float = 1.2) -> None:
        if self._app is None:
            return
        self._app.notify(message, timeout=timeout)

    def exit(self) -> None:
        if self._app is None:
            return
        self._app.exit()

    def toggle_zoom(self) -> None:
        if self._app is None:
            return
        action = getattr(self._app, "action_toggle_zoom", None)
        if callable(action):
            self._app.call_later(action)

    def open_source_find(self) -> None:
        if self._app is None:
            return
        action = getattr(self._app, "action_open_source_find", None)
        if callable(action):
            self._app.call_later(action)

    def focus_locals(self) -> None:
        if self._app is None:
            return
        action = getattr(self._app, "action_focus_locals", None)
        if callable(action):
            self._app.call_later(action)

    def focus_locals_filter(self) -> None:
        if self._app is None:
            return
        action = getattr(self._app, "action_focus_locals_filter", None)
        if callable(action):
            self._app.call_later(action)

    def expand_selected_local(self) -> None:
        if self._app is None:
            return
        action = getattr(self._app, "action_expand_selected_local", None)
        if callable(action):
            self._app.call_later(action)

    def edit_selected_local(self) -> None:
        if self._app is None:
            return
        action = getattr(self._app, "action_edit_selected_local", None)
        if callable(action):
            self._app.call_later(action)

    def push_screen(self, screen: Screen[object]) -> None:
        if self._app is None:
            return
        self._app.push_screen(screen)

    def pop_screen(self) -> None:
        if self._app is None:
            return
        self._app.pop_screen()
