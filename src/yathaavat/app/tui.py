from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable
from pathlib import Path
from typing import ClassVar

from textual import events
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
    SessionState,
    SessionStore,
    Slot,
    WidgetRegistry,
)


class YathaavatApp(App[None]):
    CSS = """
    $bg: #0b0f14;
    $bg_chrome: #070a0f;
    $bg_panel: #0e1521;
    $bg_panel_muted: #101823;
    $bg_modal: #0f1520;
    $border: #1f2a3a;
    $border_modal: #2a3b52;
    $border_focus: #3aa6ff;
    $fg: #d6e2ff;
    $fg_muted: #93a4c7;
    $fg_dim: #6e7c9a;
    $accent: #8bd5ff;
    $success: #4ade80;
    $warning: #f2c94c;
    $danger: #ff5c5c;
    $selection_bg: #12324f;
    $selection_bg_focus: #1a4b7a;
    $cursor_line_bg: #0f2033;

    Screen { background: $bg; color: $fg; }

    #status {
      dock: top;
      height: 1;
      padding: 0 1;
      background: $bg_chrome;
    }

    #help {
      dock: bottom;
      height: 1;
      padding: 0 1;
      background: $bg_chrome;
      color: $fg_muted;
    }

    #root { height: 1fr; }
    #layout { height: 1fr; }
    #bottom { height: 12; min-height: 7; }

    /* Pane zoom (maximize) */
    #root.zoom-left #center,
    #root.zoom-left #right,
    #root.zoom-left #bottom { display: none; }

    #root.zoom-center #left,
    #root.zoom-center #right,
    #root.zoom-center #bottom { display: none; }

    #root.zoom-right #left,
    #root.zoom-right #center,
    #root.zoom-right #bottom { display: none; }

    #root.zoom-bottom-left #layout { display: none; }
    #root.zoom-bottom-left #bottom { height: 1fr; min-height: 1fr; }
    #root.zoom-bottom-left #bottom_right { display: none; }

    #root.zoom-bottom-right #layout { display: none; }
    #root.zoom-bottom-right #bottom { height: 1fr; min-height: 1fr; }
    #root.zoom-bottom-right #bottom_left { display: none; }

    .pane {
      border: tall $border;
      background: $bg_panel;
    }
    .pane_empty { padding: 1 1; color: $fg_muted; }

    /* Focus ring: one obvious cue, everywhere. */
    #root.focus-left #left,
    #root.focus-center #center,
    #root.focus-right #right,
    #root.focus-bottom-left #bottom_left,
    #root.focus-bottom-right #bottom_right {
      border: tall $border_focus;
    }

    TabbedContent { height: 1fr; }
    TabPane { padding: 0 0; }

    #source_header {
      height: 1;
      padding: 0 1;
      background: $bg_panel_muted;
      color: $accent;
    }
    #source_view { height: 1fr; background: $bg; border: none; padding: 0 1; }
    #source_view .text-area--cursor-line { background: $cursor_line_bg; }
    #source_view .text-area--selection { background: $selection_bg_focus; }

    #exc_header { height: 1; padding: 0 1; background: $bg_panel_muted; color: $danger; }
    #exc_tree { height: 1fr; background: $bg; }
    #exc_tree > .tree--cursor { background: $selection_bg; }
    #exc_tree:focus > .tree--cursor { background: $selection_bg_focus; text-style: bold; }
    #exc_tree > .tree--guides { color: $fg_dim; }

    #locals_table { height: 1fr; background: $bg; }
    #watches_table { height: 1fr; background: $bg; }
    #breakpoints_table { height: 1fr; background: $bg; }

    #console_log { height: 1fr; background: $bg; }
    #console_row { height: auto; background: $bg_panel_muted; }
    #console_prompt { width: 4; color: $fg_muted; background: $bg_panel_muted; padding: 0 1; }
    #console_input { width: 1fr; background: $bg_panel_muted; }

    #transcript_log { height: 1fr; background: $bg; }

    /* Tabs / tables / lists: sharpen selection + discoverability. */
    Tabs { background: $bg_panel_muted; }
    Tab { color: $fg_muted; }
    Tab.-active { color: $fg; text-style: bold; }
    Tabs:focus .underline--bar { color: $accent; background: $bg; }
    Tabs:focus Tab.-active { background: $selection_bg; color: $fg; }

    ListView { background: $bg; }
    ListView > ListItem.-hovered { background: $bg_panel_muted; }
    ListView > ListItem.-highlight { background: $selection_bg; color: $fg; }
    ListView:focus > ListItem.-highlight { background: $selection_bg_focus; text-style: bold; }

    DataTable { background: $bg; color: $fg; }
    DataTable > .datatable--header { background: $bg_panel_muted; color: $fg; }
    DataTable > .datatable--even-row { background: $bg_panel_muted 30%; }
    DataTable > .datatable--cursor { background: $selection_bg; color: $fg; }
    DataTable:focus > .datatable--cursor { background: $selection_bg_focus; text-style: bold; }
    DataTable > .datatable--hover { background: $bg_panel_muted; }

    #pal_root {
      width: 86%;
      max-width: 120;
      height: 70%;
      border: round $border_modal;
      background: $bg_modal;
      padding: 1 1;
    }
    #pal_title { color: $accent; height: 1; }
    #pal_input { margin-top: 1; }
    #pal_list { margin-top: 1; }
    .pal_row { color: $fg; }

    #attach_root {
      width: 92%;
      max-width: 140;
      height: 80%;
      border: round $border_modal;
      background: $bg_modal;
      padding: 1 1;
    }
    #attach_title { color: $accent; height: 1; }
    #attach_input { margin-top: 1; }
    #attach_list { margin-top: 1; }
    .attach_row { color: $fg; }

    #connect_root {
      width: 70%;
      max-width: 90;
      height: 30%;
      border: round $border_modal;
      background: $bg_modal;
      padding: 1 1;
    }
    #connect_title { color: $accent; height: 1; }
    #connect_input { margin-top: 1; }
    #connect_hint { margin-top: 1; color: $fg_muted; }

    #launch_root {
      width: 86%;
      max-width: 130;
      height: 34%;
      border: round $border_modal;
      background: $bg_modal;
      padding: 1 1;
    }
    #launch_title { color: $accent; height: 1; }
    #launch_input { margin-top: 1; }
    #launch_hint { margin-top: 1; color: $fg_muted; }

    #bp_root {
      width: 70%;
      max-width: 110;
      height: 30%;
      border: round $border_modal;
      background: $bg_modal;
      padding: 1 1;
    }
    #bp_title { color: $accent; height: 1; }
    #bp_input { margin-top: 1; }
    #bp_hint { margin-top: 1; color: $fg_muted; }

    #bpedit_root {
      dock: bottom;
      margin: 0 2 1 2;
      width: 1fr;
      max-width: 140;
      height: 12;
      border: round $border_modal;
      background: $bg_modal;
      padding: 1 1;
    }
    #bpedit_title { color: $accent; height: 1; }
    #bpedit_condition { margin-top: 1; }
    #bpedit_hit { margin-top: 1; }
    #bpedit_log { margin-top: 1; }
    #bpedit_hint { margin-top: 1; color: $fg_muted; height: 1; }

    #find_root {
      dock: bottom;
      margin: 0;
      width: 1fr;
      height: 2;
      border: none;
      background: $bg_panel_muted;
      padding: 0 1;
    }
    #find_row { height: 1; }
    #find_title { color: $accent; width: 6; }
    #find_input { width: 1fr; margin: 0 1; }
    #find_status { color: $fg_muted; width: 14; }
    #find_hint { color: $fg_muted; height: 1; }

    #goto_root {
      width: 70%;
      max-width: 110;
      height: 30%;
      border: round $border_modal;
      background: $bg_modal;
      padding: 1 1;
    }
    #goto_title { color: $accent; height: 1; }
    #goto_input { margin-top: 1; }
    #goto_hint { margin-top: 1; color: $fg_muted; }

    #watch_root {
      dock: bottom;
      margin: 0 2 1 2;
      width: 1fr;
      max-width: 140;
      height: 8;
      border: round $border_modal;
      background: $bg_modal;
      padding: 1 1;
    }
    #watch_row { height: auto; }
    #watch_title { color: $accent; width: 6; }
    #watch_input { width: 1fr; margin: 0 1; }
    #watch_status { color: $fg_muted; width: 8; }
    #watch_hint { margin-top: 0; color: $fg_muted; height: 1; }

    /* Inputs: compact by default, obvious focus. */
    Input { background: $bg_panel_muted; color: $fg; border: tall $border; padding: 0 1; }
    Input:focus { border: tall $border_focus; }
    #find_input { border: none; background: $bg_panel_muted; padding: 0 1; }

    /* Expression editors (console/watch): TextArea + inline completion list. */
    .expr_area {
      height: 1;
      border: none;
      background: $bg_panel_muted;
      padding: 0 1;
    }
    .expr_completions {
      height: 6;
      margin: 0 0;
      border: tall $border;
      background: $bg_modal;
    }
    #watch_input .expr_completions { height: 4; }
    .expr_completions:focus {
      border: tall $border_focus;
    }
    .expr_completion_row { color: $fg; }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        ("ctrl+p", "open_palette", "Palette"),
        ("f6", "focus_next", "Focus"),
        ("shift+f6", "focus_previous", "Focus (prev)"),
        ("ctrl+\\", "command('session.disconnect')", "Disconnect"),
        ("ctrl+d", "command('session.disconnect')", "Disconnect (alt)"),
        ("ctrl+shift+\\", "command('session.terminate')", "Terminate"),
        ("ctrl+x", "command('session.terminate')", "Terminate (alt)"),
    ]
    ENABLE_COMMAND_PALETTE: ClassVar[bool] = False

    def __init__(self, *, ctx: AppContext, plugin_errors: list[str]) -> None:
        super().__init__()
        self._ctx = ctx
        self._plugin_errors = plugin_errors
        self._status = StatusLine()
        self._help = HelpLine()
        self._status_unsubscribe: Callable[[], None] | None = None
        self._zoom_mode: str | None = None
        self._focus_mode: str | None = None
        self._last_snapshot: SessionSnapshot | None = None
        self._root_container: Container | None = None
        self._status_flash: str | None = None
        self._status_flash_task: asyncio.Task[None] | None = None

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
        self._root_container = self.query_one("#root", Container)
        self.call_later(self._focus_default)
        self.call_after_refresh(self._sync_focus_ring)

    def on_unmount(self) -> None:
        if self._status_unsubscribe is not None:
            self._status_unsubscribe()
        self._status_unsubscribe = None
        if self._status_flash_task is not None:
            self._status_flash_task.cancel()
            self._status_flash_task = None

    def _bind_status(self) -> None:
        store: SessionStore | None
        try:
            store = self._ctx.services.get(SESSION_STORE)
        except KeyError:
            store = None

        if store is None:
            self._last_snapshot = None
            self._set_status(None)
            return

        def _on(s: SessionSnapshot) -> None:
            self._last_snapshot = s
            self._set_status(s)

        self._status_unsubscribe = store.subscribe(_on)

    def _set_status(self, snapshot: SessionSnapshot | None) -> None:
        if snapshot is None:
            message = "Ctrl+P palette"
            state = "DISCONNECTED"
            pid: int | None = None
            py = _runtime_python()
            backend = ""
        else:
            message = _status_message(snapshot) or "Ctrl+P palette"
            state = snapshot.state.value
            pid = snapshot.pid
            py = snapshot.python or _runtime_python()
            backend = snapshot.backend

        if self._status_flash:
            message = f"{message}  •  {self._status_flash}" if message else self._status_flash

        zoom_pill: str | None = None
        zoom = self._zoom_mode
        if zoom is not None:
            label = zoom.removeprefix("zoom-").replace("-", " ").strip()
            zoom_pill = f"ZOOM {label}"

        self._status.set(
            StatusSnapshot(
                workspace=str(Path.cwd()),
                state=state,
                pid=pid,
                python=py,
                backend=backend,
                zoom=zoom_pill,
                plugin_errors=len(self._plugin_errors),
                message=message,
            )
        )

    def action_open_palette(self) -> None:
        self.push_screen(CommandPalette(ctx=self._ctx))

    async def action_command(self, command_id: str) -> None:
        cmd = self._ctx.commands.get(command_id)
        self._flash_status(_flash_label_for_command(cmd.spec.id, cmd.spec.title))
        try:
            await cmd.run()
        except Exception as exc:
            # Many commands already handle and notify, but always surface errors
            # so the user clearly sees that the action failed.
            self._flash_status(f"✗ {cmd.spec.title}", timeout=2.0)
            self.notify(str(exc), timeout=2.5)

    def action_open_source_find(self) -> None:
        try:
            editor = self.query_one("#source_view")
        except Exception:
            self.notify("Source view not available.", timeout=2.0)
            return

        panel = getattr(editor, "parent", None)
        open_find = getattr(panel, "open_find", None)
        if callable(open_find):
            open_find()
            return

        self.notify("Find is not available.", timeout=2.0)

    def action_toggle_zoom(self) -> None:
        root = self._root_container or self.query_one("#root", Container)
        current = self._zoom_mode
        if current is not None:
            root.remove_class(current)
            self._zoom_mode = None
            self._set_status(self._last_snapshot)
            return

        mode = _zoom_target_for_focus(self.focused)
        root.add_class(mode)
        self._zoom_mode = mode
        self._set_status(self._last_snapshot)

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        self._sync_focus_ring(event.control)

    def on_descendant_blur(self, _event: events.DescendantBlur) -> None:
        self._sync_focus_ring(self.focused)

    def _sync_focus_ring(self, focused: object | None = None) -> None:
        root = self._root_container
        if root is None:
            return

        mode = _focus_target_for_focus(focused or self.focused)
        if mode == self._focus_mode:
            return
        if self._focus_mode is not None:
            root.remove_class(self._focus_mode)
        root.add_class(mode)
        self._focus_mode = mode

    def _focus_default(self) -> None:
        try:
            self.query_one("#source_view").focus()
        except Exception:
            return

    def _flash_status(self, message: str, *, timeout: float = 1.0) -> None:
        """Show a short-lived status message in the top bar.

        This complements transcript logging: it provides immediate feedback that a keypress
        was received and an action started.
        """

        self._status_flash = message
        self._set_status(self._last_snapshot)

        if self._status_flash_task is not None:
            self._status_flash_task.cancel()

        async def _clear() -> None:
            try:
                await asyncio.sleep(timeout)
            except asyncio.CancelledError:
                return
            self._status_flash = None
            self._set_status(self._last_snapshot)

        self._status_flash_task = asyncio.create_task(_clear())


def _flash_label_for_command(command_id: str, title: str) -> str:
    # Keep this short; it lives in a 1-line status bar.
    match command_id:
        case (
            "debug.continue"
            | "debug.pause"
            | "debug.step_over"
            | "debug.step_in"
            | "debug.step_out"
            | "debug.run_to_cursor"
            | "breakpoint.toggle"
            | "breakpoint.add"
            | "session.disconnect"
            | "session.terminate"
        ):
            return f"{title}…"
        case _:
            return title


def _help_text(ctx: AppContext) -> str:
    def label(command_id: str, title: str) -> str | None:
        try:
            cmd = ctx.commands.get(command_id)
        except KeyError:
            return None
        if not cmd.spec.default_keys:
            return title
        keys = cmd.spec.default_keys[:2]
        key = " / ".join(format_key(k) for k in keys)
        return f"{key} {title}".strip()

    parts = [
        "Ctrl+P palette",
        label("session.attach", "attach"),
        label("session.connect", "connect"),
        label("session.launch", "launch"),
        label("session.disconnect", "disconnect"),
        label("session.terminate", "terminate"),
        label("view.zoom", "zoom"),
        label("debug.continue", "continue"),
        label("debug.run_to_cursor", "run-to-cursor"),
        label("debug.step_over", "next"),
        label("debug.step_in", "step"),
        label("debug.step_out", "out"),
        label("source.jump_to_exec", "exec"),
        label("source.find", "find"),
        label("source.goto", "goto"),
        label("watch.add", "watch"),
        label("breakpoint.add", "add bp"),
        label("breakpoint.toggle", "breakpoint"),
        label("app.quit", "quit"),
    ]
    return "  •  ".join([p for p in parts if p])


def _runtime_python() -> str:
    v = sys.version_info
    return f"{v.major}.{v.minor}.{v.micro}"


def _status_message(snapshot: SessionSnapshot) -> str:
    if snapshot.state != SessionState.PAUSED:
        return ""

    parts: list[str] = []

    def fmt_loc(path: str, line: int, col: int | None = None) -> str:
        try:
            name = Path(path).name
        except Exception:
            name = path
        loc = f"{name}:{line}"
        if isinstance(col, int):
            loc = f"{loc}:{col}"
        return loc

    frames = snapshot.frames
    frame_id = snapshot.selected_frame_id or (frames[0].id if frames else None)
    frame = next((f for f in frames if f.id == frame_id), None)
    exec_path = frame.path if frame is not None else None
    exec_line = frame.line if frame is not None else None

    cursor_path = snapshot.source_path
    cursor_line = snapshot.source_line
    cursor_col = snapshot.source_col if isinstance(snapshot.source_col, int) else None

    if isinstance(exec_path, str) and isinstance(exec_line, int):
        parts.append(fmt_loc(exec_path, exec_line))
    elif isinstance(cursor_path, str) and isinstance(cursor_line, int):
        parts.append(fmt_loc(cursor_path, cursor_line, cursor_col))

    if frame is not None and frame.name:
        parts.append(frame.name)

    thread = snapshot.selected_thread_id
    if isinstance(thread, int):
        parts.append(f"T{thread}")

    if snapshot.stop_reason:
        parts.append(snapshot.stop_reason)

    if (
        isinstance(exec_path, str)
        and isinstance(exec_line, int)
        and isinstance(cursor_path, str)
        and isinstance(cursor_line, int)
        and (cursor_path != exec_path or cursor_line != exec_line)
    ):
        if cursor_path == exec_path:
            src = f"src {cursor_line}"
        else:
            src = f"src {fmt_loc(cursor_path, cursor_line)}"
        if cursor_col is not None:
            src = f"{src}:{cursor_col}"
        parts.append(src)

    return "  •  ".join(parts)


def _zoom_target_for_focus(focused: object) -> str:
    mapping = {
        "left": "zoom-left",
        "center": "zoom-center",
        "right": "zoom-right",
        "bottom_left": "zoom-bottom-left",
        "bottom_right": "zoom-bottom-right",
    }
    w = focused
    while w is not None:
        wid = getattr(w, "id", None)
        if isinstance(wid, str) and wid in mapping:
            return mapping[wid]
        w = getattr(w, "parent", None)
    return "zoom-center"


def _focus_target_for_focus(focused: object) -> str:
    mapping = {
        "left": "focus-left",
        "center": "focus-center",
        "right": "focus-right",
        "bottom_left": "focus-bottom-left",
        "bottom_right": "focus-bottom-right",
    }
    w = focused
    while w is not None:
        wid = getattr(w, "id", None)
        if isinstance(wid, str) and wid in mapping:
            return mapping[wid]
        w = getattr(w, "parent", None)
    return "focus-center"


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
