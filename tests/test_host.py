from __future__ import annotations

from typing import Any, cast

from yathaavat.app.host import TextualUiHost


def test_textual_ui_host_noops_until_bound_and_delegates_after_bind() -> None:
    class _TestApp:
        def __init__(self) -> None:
            self.notifications: list[tuple[str, float]] = []
            self.later: list[object] = []
            self.screens: list[object] = []
            self.exited = False
            self.popped = 0

        def notify(self, message: str, *, timeout: float) -> None:
            self.notifications.append((message, timeout))

        def exit(self) -> None:
            self.exited = True

        def action_toggle_zoom(self) -> None:
            self.later.append("zoom")

        def action_open_source_find(self) -> None:
            self.later.append("find")

        def call_later(self, action: object) -> None:
            self.later.append(action)

        def push_screen(self, screen: object) -> None:
            self.screens.append(screen)

        def pop_screen(self) -> None:
            self.popped += 1

    host = TextualUiHost()
    host.notify("ignored")
    host.exit()

    app = _TestApp()
    assert host.bind(cast(Any, app)) is host
    host.notify("hello", timeout=2.0)
    host.toggle_zoom()
    host.open_source_find()
    host.push_screen(cast(Any, object()))
    host.pop_screen()
    host.exit()

    assert app.notifications == [("hello", 2.0)]
    assert len(app.later) == 2
    assert len(app.screens) == 1
    assert app.popped == 1
    assert app.exited is True
