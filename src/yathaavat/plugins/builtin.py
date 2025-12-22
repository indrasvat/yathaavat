from __future__ import annotations

from dataclasses import dataclass
from typing import override

from yathaavat.app.breakpoint import BreakpointDialog
from yathaavat.app.panels import (
    BreakpointsPanel,
    ConsolePanel,
    LocalsPanel,
    SourcePanel,
    StackPanel,
    TranscriptPanel,
)
from yathaavat.app.source_nav import FindDialog, GotoDialog
from yathaavat.core import (
    SESSION_MANAGER,
    SESSION_STORE,
    AppContext,
    Command,
    CommandSpec,
    Plugin,
    RunToCursorManager,
    SessionManager,
    SessionSnapshot,
    SessionState,
    Slot,
    WidgetContribution,
)


def _session(ctx: AppContext) -> SessionManager | None:
    try:
        return ctx.services.get(SESSION_MANAGER)
    except KeyError:
        return None


def _snapshot(ctx: AppContext) -> SessionSnapshot:
    return ctx.services.get(SESSION_STORE).snapshot()


@dataclass(frozen=True, slots=True)
class BuiltinPlugin(Plugin):
    @property
    @override
    def id(self) -> str:
        return "builtin"

    @override
    def register(self, ctx: AppContext) -> None:
        host = ctx.host

        async def _quit() -> None:
            session = _session(ctx)
            if session is not None:
                try:
                    await session.shutdown()
                except Exception as exc:
                    host.notify(str(exc), timeout=2.5)
            host.exit()

        async def _resume() -> None:
            session = _session(ctx)
            if session is None:
                host.notify("continue (prototype)")
                return
            try:
                await session.resume()
            except Exception as exc:
                host.notify(str(exc), timeout=2.5)

        async def _pause() -> None:
            session = _session(ctx)
            if session is None:
                host.notify("pause (prototype)")
                return
            try:
                await session.pause()
            except Exception as exc:
                host.notify(str(exc), timeout=2.5)

        async def _step_over() -> None:
            session = _session(ctx)
            if session is None:
                host.notify("step over (prototype)")
                return
            try:
                await session.step_over()
            except Exception as exc:
                host.notify(str(exc), timeout=2.5)

        async def _step_in() -> None:
            session = _session(ctx)
            if session is None:
                host.notify("step in (prototype)")
                return
            try:
                await session.step_in()
            except Exception as exc:
                host.notify(str(exc), timeout=2.5)

        async def _toggle_breakpoint() -> None:
            session = _session(ctx)
            if session is None:
                host.notify("toggle breakpoint (prototype)")
                return

            snap = _snapshot(ctx)
            try:
                if snap.source_path is not None and isinstance(snap.source_line, int):
                    await session.toggle_breakpoint(snap.source_path, snap.source_line)
                    return

                frame_id = snap.selected_frame_id or (snap.frames[0].id if snap.frames else None)
                frame = next((f for f in snap.frames if f.id == frame_id), None)
                if frame is None or frame.path is None or frame.line is None:
                    host.notify("No source location for breakpoint.", timeout=2.0)
                    return
                await session.toggle_breakpoint(frame.path, frame.line)
            except Exception as exc:
                host.notify(str(exc), timeout=2.5)

        async def _run_to_cursor() -> None:
            session = _session(ctx)
            if session is None:
                host.notify("run to cursor (prototype)")
                return

            snap = _snapshot(ctx)
            if snap.state != SessionState.PAUSED:
                host.notify("Run to cursor requires PAUSED state.", timeout=2.0)
                return

            path = snap.source_path
            line = snap.source_line
            if not path or not isinstance(line, int):
                host.notify("No source location selected.", timeout=2.0)
                return

            if not isinstance(session, RunToCursorManager):
                host.notify("Run to cursor is not supported by this backend.", timeout=2.0)
                return

            try:
                await session.run_to_cursor(path, line)
            except Exception as exc:
                host.notify(str(exc), timeout=2.5)

        ctx.commands.register(
            Command(
                CommandSpec(
                    id="app.quit",
                    title="Quit",
                    summary="Exit yathaavat.",
                    default_keys=("ctrl+q",),
                ),
                handler=_quit,
            )
        )

        ctx.commands.register(
            Command(
                CommandSpec(
                    id="debug.continue",
                    title="Continue",
                    summary="Resume execution (prototype).",
                    default_keys=("f5", "c"),
                ),
                handler=_resume,
            )
        )

        ctx.commands.register(
            Command(
                CommandSpec(
                    id="debug.pause",
                    title="Pause",
                    summary="Pause execution (prototype).",
                    default_keys=("p",),
                ),
                handler=_pause,
            )
        )

        ctx.commands.register(
            Command(
                CommandSpec(
                    id="debug.step_over",
                    title="Step Over",
                    summary="Step over (prototype).",
                    default_keys=("f10", "n"),
                ),
                handler=_step_over,
            )
        )

        ctx.commands.register(
            Command(
                CommandSpec(
                    id="debug.step_in",
                    title="Step In",
                    summary="Step in (prototype).",
                    default_keys=("f11", "s"),
                ),
                handler=_step_in,
            )
        )

        ctx.commands.register(
            Command(
                CommandSpec(
                    id="debug.run_to_cursor",
                    title="Run to Cursor",
                    summary="Continue until the source cursor location is reached.",
                    default_keys=("ctrl+f10",),
                ),
                handler=_run_to_cursor,
            )
        )

        ctx.commands.register(
            Command(
                CommandSpec(
                    id="source.find",
                    title="Find…",
                    summary="Find text in the Source panel.",
                    default_keys=("ctrl+f",),
                ),
                handler=lambda: ctx.host.push_screen(FindDialog(ctx=ctx)),
            )
        )

        ctx.commands.register(
            Command(
                CommandSpec(
                    id="source.goto",
                    title="Go to Line…",
                    summary="Jump to a line[:col] in the Source panel.",
                    default_keys=("ctrl+g",),
                ),
                handler=lambda: ctx.host.push_screen(GotoDialog(ctx=ctx)),
            )
        )

        ctx.commands.register(
            Command(
                CommandSpec(
                    id="breakpoint.toggle",
                    title="Toggle Breakpoint",
                    summary="Toggle breakpoint at cursor (prototype).",
                    default_keys=("f9", "b"),
                ),
                handler=_toggle_breakpoint,
            )
        )
        ctx.commands.register(
            Command(
                CommandSpec(
                    id="breakpoint.add",
                    title="Add Breakpoint…",
                    summary="Toggle breakpoint by file:line (queues when disconnected).",
                    default_keys=("ctrl+b",),
                ),
                handler=lambda: ctx.host.push_screen(BreakpointDialog(ctx=ctx)),
            )
        )

        ctx.widgets.register(
            WidgetContribution(
                id="builtin.stack",
                title="Stack",
                slot=Slot.LEFT,
                factory=lambda _ctx: StackPanel(ctx=_ctx),
            )
        )
        ctx.widgets.register(
            WidgetContribution(
                id="builtin.source",
                title="Source",
                slot=Slot.CENTER,
                factory=lambda _ctx: SourcePanel(ctx=_ctx),
            )
        )
        ctx.widgets.register(
            WidgetContribution(
                id="builtin.locals",
                title="Locals",
                slot=Slot.RIGHT,
                factory=lambda _ctx: LocalsPanel(ctx=_ctx),
            )
        )
        ctx.widgets.register(
            WidgetContribution(
                id="builtin.breakpoints",
                title="Breakpoints",
                slot=Slot.RIGHT,
                factory=lambda _ctx: BreakpointsPanel(ctx=_ctx),
            )
        )
        ctx.widgets.register(
            WidgetContribution(
                id="builtin.console",
                title="Console",
                slot=Slot.BOTTOM_LEFT,
                factory=lambda _ctx: ConsolePanel(ctx=_ctx),
            )
        )
        ctx.widgets.register(
            WidgetContribution(
                id="builtin.transcript",
                title="Transcript",
                slot=Slot.BOTTOM_RIGHT,
                factory=lambda _ctx: TranscriptPanel(ctx=_ctx),
            )
        )


def plugin() -> Plugin:
    return BuiltinPlugin()
