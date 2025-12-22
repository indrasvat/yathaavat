from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.binding import BindingType
from textual.containers import Container, Horizontal

from yathaavat.app.chrome import HelpLine, StatusLine, StatusSnapshot
from yathaavat.app.host import TextualUiHost
from yathaavat.app.keys import format_key
from yathaavat.app.layout import SlotDescriptor, SlotTabs
from yathaavat.app.palette import CommandPalette
from yathaavat.core import (
    SESSION_STORE,
    AppContext,
    CommandRegistry,
    PluginManager,
    ServiceRegistry,
    SessionSnapshot,
    SessionStore,
    Slot,
    WidgetRegistry,
)


class YathaavatApp(App[None]):
    CSS = """
    Screen { background: #0b0f14; color: #d6e2ff; }

    #status {
      dock: top;
      height: 1;
      padding: 0 1;
      background: #070a0f;
    }

    #help {
      dock: bottom;
      height: 1;
      padding: 0 1;
      background: #070a0f;
      color: #93a4c7;
    }

    #root { height: 1fr; }
    #layout { height: 1fr; }
    #bottom { height: 12; min-height: 7; }

    .pane {
      border: tall #1f2a3a;
      background: #0e1521;
    }
    .pane_empty { padding: 1 1; color: #93a4c7; }

    TabbedContent { height: 1fr; }
    TabPane { padding: 0 0; }

    #source_header {
      height: 1;
      padding: 0 1;
      background: #0b1a2a;
      color: #8bd5ff;
    }
    #source_view { height: 1fr; background: #0b0f14; }

    #locals_table { height: 1fr; background: #0b0f14; }
    #breakpoints_table { height: 1fr; background: #0b0f14; }

    #console_log { height: 1fr; background: #0b0f14; }
    #console_input { height: 1; }

    #transcript_log { height: 1fr; background: #0b0f14; }

    #pal_root {
      width: 86%;
      max-width: 120;
      height: 70%;
      border: round #2a3b52;
      background: #0f1520;
      padding: 1 1;
    }
    #pal_title { color: #8bd5ff; height: 1; }
    #pal_input { margin-top: 1; }
    #pal_list { margin-top: 1; }
    .pal_row { color: #d6e2ff; }

    #attach_root {
      width: 92%;
      max-width: 140;
      height: 80%;
      border: round #2a3b52;
      background: #0f1520;
      padding: 1 1;
    }
    #attach_title { color: #8bd5ff; height: 1; }
    #attach_input { margin-top: 1; }
    #attach_list { margin-top: 1; }
    .attach_row { color: #d6e2ff; }

    #connect_root {
      width: 70%;
      max-width: 90;
      height: 30%;
      border: round #2a3b52;
      background: #0f1520;
      padding: 1 1;
    }
    #connect_title { color: #8bd5ff; height: 1; }
    #connect_input { margin-top: 1; }
    #connect_hint { margin-top: 1; color: #93a4c7; }

    #launch_root {
      width: 86%;
      max-width: 130;
      height: 34%;
      border: round #2a3b52;
      background: #0f1520;
      padding: 1 1;
    }
    #launch_title { color: #8bd5ff; height: 1; }
    #launch_input { margin-top: 1; }
    #launch_hint { margin-top: 1; color: #93a4c7; }

    #bp_root {
      width: 70%;
      max-width: 110;
      height: 30%;
      border: round #2a3b52;
      background: #0f1520;
      padding: 1 1;
    }
    #bp_title { color: #8bd5ff; height: 1; }
    #bp_input { margin-top: 1; }
    #bp_hint { margin-top: 1; color: #93a4c7; }
    """

    BINDINGS: ClassVar[list[BindingType]] = [("ctrl+p", "open_palette", "Palette")]
    ENABLE_COMMAND_PALETTE: ClassVar[bool] = False

    def __init__(self, *, ctx: AppContext, plugin_errors: list[str]) -> None:
        super().__init__()
        self._ctx = ctx
        self._plugin_errors = plugin_errors
        self._status = StatusLine()
        self._help = HelpLine()
        self._status_unsubscribe: Callable[[], None] | None = None

    def compose(self) -> ComposeResult:
        yield self._status

        left = SlotTabs(
            ctx=self._ctx,
            slot=SlotDescriptor(slot=Slot.LEFT, fallback_title="Left"),
            id="left",
        )
        center = SlotTabs(
            ctx=self._ctx,
            slot=SlotDescriptor(slot=Slot.CENTER, fallback_title="Source"),
            id="center",
        )
        right = SlotTabs(
            ctx=self._ctx,
            slot=SlotDescriptor(slot=Slot.RIGHT, fallback_title="Right"),
            id="right",
        )

        bottom_left = SlotTabs(
            ctx=self._ctx,
            slot=SlotDescriptor(slot=Slot.BOTTOM_LEFT, fallback_title="Console"),
            id="bottom_left",
        )
        bottom_right = SlotTabs(
            ctx=self._ctx,
            slot=SlotDescriptor(slot=Slot.BOTTOM_RIGHT, fallback_title="Transcript"),
            id="bottom_right",
        )

        yield Container(
            Horizontal(left, center, right, id="layout"),
            Horizontal(bottom_left, bottom_right, id="bottom"),
            id="root",
        )
        yield self._help

    def on_mount(self) -> None:
        for command in self._ctx.commands.all():
            for key in command.spec.default_keys:
                self.bind(
                    key,
                    f"command({command.spec.id!r})",
                    description=command.spec.title,
                )

        self._bind_status()
        self._help.set_text(_help_text(self._ctx))

    def on_unmount(self) -> None:
        if self._status_unsubscribe is not None:
            self._status_unsubscribe()
        self._status_unsubscribe = None

    def _bind_status(self) -> None:
        store: SessionStore | None
        try:
            store = self._ctx.services.get(SESSION_STORE)
        except KeyError:
            store = None

        if store is None:
            self._status.set(
                StatusSnapshot(
                    workspace=str(Path.cwd()),
                    state="DISCONNECTED",
                    pid=None,
                    python=_runtime_python(),
                    backend="",
                    plugin_errors=len(self._plugin_errors),
                    message="Ctrl+P palette",
                )
            )
            return

        def _on(s: SessionSnapshot) -> None:
            self._status.set(
                StatusSnapshot(
                    workspace=str(Path.cwd()),
                    state=s.state.value,
                    pid=s.pid,
                    python=s.python or _runtime_python(),
                    backend=s.backend,
                    plugin_errors=len(self._plugin_errors),
                    message="Ctrl+P palette",
                )
            )

        self._status_unsubscribe = store.subscribe(_on)

    def action_open_palette(self) -> None:
        self.push_screen(CommandPalette(ctx=self._ctx))

    async def action_command(self, command_id: str) -> None:
        await self._ctx.commands.get(command_id).run()


def _help_text(ctx: AppContext) -> str:
    def label(command_id: str, title: str) -> str | None:
        try:
            cmd = ctx.commands.get(command_id)
        except KeyError:
            return None
        if not cmd.spec.default_keys:
            return title
        key = format_key(cmd.spec.default_keys[0])
        return f"{key} {title}".strip()

    parts = [
        "Ctrl+P palette",
        label("session.attach", "attach"),
        label("session.connect", "connect"),
        label("session.launch", "launch"),
        label("session.disconnect", "disconnect"),
        label("session.terminate", "terminate"),
        label("debug.continue", "continue"),
        label("debug.run_to_cursor", "run-to-cursor"),
        label("debug.step_over", "next"),
        label("debug.step_in", "step"),
        label("breakpoint.add", "add bp"),
        label("breakpoint.toggle", "breakpoint"),
        label("app.quit", "quit"),
    ]
    return "  •  ".join([p for p in parts if p])


def _runtime_python() -> str:
    v = sys.version_info
    return f"{v.major}.{v.minor}.{v.micro}"


def run_tui() -> None:
    commands = CommandRegistry()
    widgets = WidgetRegistry()
    host = TextualUiHost()
    services = ServiceRegistry()
    services.register(SESSION_STORE, SessionStore())
    ctx = AppContext(commands=commands, widgets=widgets, services=services, host=host)

    pm = PluginManager()
    plugins, errors = pm.load()
    for plugin in plugins:
        plugin.register(ctx)

    app = YathaavatApp(ctx=ctx, plugin_errors=[e.plugin_name for e in errors])
    host.bind(app)
    app.run()
