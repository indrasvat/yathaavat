from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

import pytest
from textual.widgets import Static

import yathaavat.app.tui as tui
from tests.support import make_context
from yathaavat.app.tui import (
    YathaavatApp,
    _flash_label_for_command,
    _focus_target_for_focus,
    _help_text,
    _status_message,
    _zoom_target_for_focus,
)
from yathaavat.core import (
    SESSION_STORE,
    AppContext,
    Command,
    CommandSpec,
    FrameInfo,
    Plugin,
    SessionState,
    Slot,
    WidgetContribution,
)
from yathaavat.core.plugins import PluginLoadError


@dataclass(frozen=True, slots=True)
class _FocusNode:
    id: str | None
    parent: object | None = None


def test_tui_helpers_format_status_help_and_focus_targets(tmp_path: Path) -> None:
    ctx = make_context()
    ctx.commands.register(
        Command(
            CommandSpec(
                id="debug.continue",
                title="Continue",
                summary="resume",
                default_keys=("f5", "c"),
            ),
            handler=lambda: None,
        )
    )
    assert _help_text(ctx) == "Ctrl+P palette  •  F5 / C continue"
    assert _flash_label_for_command("debug.continue", "Continue") == "Continue…"
    assert _flash_label_for_command("custom.action", "Custom") == "Custom"

    source = tmp_path / "svc.py"
    source.write_text("print('ok')\n", encoding="utf-8")
    ctx.services.get(SESSION_STORE).update(
        state=SessionState.PAUSED,
        source_path=str(source),
        source_line=5,
        source_col=3,
        frames=(FrameInfo(id=7, name="handler", path=str(source), line=2),),
        selected_frame_id=7,
        selected_thread_id=99,
        stop_reason="breakpoint",
    )
    message = _status_message(ctx.services.get(SESSION_STORE).snapshot())
    assert message == "svc.py:2  •  handler  •  T99  •  breakpoint  •  src 5:3"

    focused = _FocusNode("source_view", _FocusNode("center"))
    assert _zoom_target_for_focus(focused) == "zoom-center"
    assert _focus_target_for_focus(_FocusNode("watches_table", _FocusNode("bottom_right"))) == (
        "focus-bottom-right"
    )
    assert _zoom_target_for_focus(_FocusNode(None)) == "zoom-center"


def test_yathaavat_app_mounts_status_runs_commands_and_toggles_zoom() -> None:
    async def run() -> None:
        calls: list[str] = []
        ctx = make_context()
        ctx.commands.register(
            Command(
                CommandSpec(
                    id="source.goto", title="Goto", summary="goto", default_keys=("ctrl+g",)
                ),
                handler=lambda: calls.append("ok"),
            )
        )

        def fail() -> None:
            calls.append("fail")
            raise RuntimeError("boom")

        ctx.commands.register(
            Command(CommandSpec(id="demo.fail", title="Demo Fail", summary="fail"), handler=fail)
        )
        ctx.widgets.register(
            WidgetContribution(
                id="builtin.source",
                title="Source",
                slot=Slot.CENTER,
                factory=lambda _ctx: Static("source", id="source_view"),
            )
        )
        app = YathaavatApp(ctx=ctx, plugin_errors=["bad-plugin"])

        async with app.run_test() as pilot:
            await pilot.pause()
            root = app.query_one("#root")
            assert str(app._help.content) == "Ctrl+P palette  •  Ctrl+G goto"

            app.action_toggle_zoom()
            assert "zoom-center" in root.classes
            app.action_toggle_zoom()
            assert "zoom-center" not in root.classes

            await app.action_command("source.goto")
            await app.action_command("demo.fail")
            assert calls == ["ok", "fail"]

            app.action_open_source_find()
            app._flash_status("working", timeout=0.01)
            assert app._status_flash == "working"
            await asyncio.sleep(0.02)
            assert app._status_flash is None

    asyncio.run(run())


def test_yathaavat_app_notifies_when_target_widgets_are_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        ctx = make_context()
        app = YathaavatApp(ctx=ctx, plugin_errors=[])
        notifications: list[tuple[str, float]] = []

        def notify(message: str, **kwargs: Any) -> None:
            timeout = kwargs.get("timeout", 1.2)
            assert isinstance(timeout, int | float)
            notifications.append((message, float(timeout)))

        monkeypatch.setattr(app, "notify", notify)

        async with app.run_test() as pilot:
            await pilot.pause()
            notifications.clear()
            app.action_open_source_find()
            app.action_focus_locals()
            app.action_focus_locals_filter()
            await app.action_expand_selected_local()
            await app.action_edit_selected_local()

        assert notifications == [
            ("Source view not available.", 2.0),
            ("Locals panel is not available.", 2.0),
            ("Locals filter is not available.", 2.0),
            ("Locals panel is not available.", 2.0),
            ("Locals panel is not available.", 2.0),
        ]

    asyncio.run(run())


def test_yathaavat_app_awaits_custom_locals_actions() -> None:
    async def run() -> None:
        calls: list[str] = []
        ctx = make_context()

        class _LocalsTable(Static):
            def __init__(self) -> None:
                super().__init__("locals", id="locals_table")

            def action_toggle_expand(self) -> object:
                async def expand() -> None:
                    await asyncio.sleep(0)
                    calls.append("expanded")

                return expand()

            def action_edit_value(self) -> object:
                async def edit() -> None:
                    await asyncio.sleep(0)
                    calls.append("edited")

                return edit()

        ctx.widgets.register(
            WidgetContribution(
                id="builtin.locals",
                title="Locals",
                slot=Slot.RIGHT,
                factory=lambda _ctx: _LocalsTable(),
            )
        )
        app = YathaavatApp(ctx=ctx, plugin_errors=[])

        async with app.run_test() as pilot:
            await pilot.pause()
            await app.action_expand_selected_local()
            await app.action_edit_selected_local()

        assert calls == ["expanded", "edited"]

    asyncio.run(run())


def test_run_tui_loads_plugins_binds_host_and_passes_plugin_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registered: list[AppContext] = []

    class FakePlugin(Plugin):
        @property
        def id(self) -> str:
            return "fake"

        def register(self, ctx: AppContext) -> None:
            registered.append(ctx)

    class FakePluginManager:
        def load(self) -> tuple[list[Plugin], list[PluginLoadError]]:
            return [FakePlugin()], [PluginLoadError("broken", RuntimeError("boom"))]

    class FakeApp:
        instances: ClassVar[list[FakeApp]] = []

        def __init__(self, *, ctx: AppContext, plugin_errors: list[str]) -> None:
            self.ctx = ctx
            self.plugin_errors = plugin_errors
            self.ran = False
            FakeApp.instances.append(self)

        def run(self, *_args: Any, **_kwargs: Any) -> None:
            self.ran = True

    monkeypatch.setattr(tui, "PluginManager", FakePluginManager)
    monkeypatch.setattr(tui, "YathaavatApp", FakeApp)

    tui.run_tui()

    assert len(registered) == 1
    assert FakeApp.instances[-1].ctx is registered[0]
    assert FakeApp.instances[-1].plugin_errors == ["broken"]
    assert FakeApp.instances[-1].ran is True
