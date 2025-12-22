from __future__ import annotations

import asyncio
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from textual import on
from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from yathaavat.core import (
    SESSION_MANAGER,
    SESSION_STORE,
    AppContext,
    BreakpointConfigManager,
    BreakpointInfo,
    SessionManager,
)


@dataclass(frozen=True, slots=True)
class BreakpointSpec:
    path: str
    line: int
    condition: str | None = None
    hit_condition: str | None = None
    log_message: str | None = None


def parse_breakpoint_spec(
    value: str, *, default_path: str | None = None, cwd: Path | None = None
) -> BreakpointSpec | None:
    s = value.strip()
    if not s:
        return None

    try:
        tokens = shlex.split(s, posix=True)
    except ValueError:
        tokens = s.split()

    if not tokens:
        return None

    loc = tokens[0]
    opts = tokens[1:]

    line_num: int | None = None
    if loc.isdigit():
        if default_path is None:
            return None
        line_num = int(loc)
        if line_num <= 0:
            return None
        path = str(Path(default_path).expanduser().resolve())
        spec = BreakpointSpec(path=path, line=line_num)
        return _apply_bp_opts(spec, opts)

    cwd = cwd or Path.cwd()
    path_part = loc

    if "#L" in loc:
        left, right = loc.rsplit("#L", 1)
        if right.strip().isdigit():
            path_part = left
            line_num = int(right.strip())
    elif ":" in loc:
        left, right = loc.rsplit(":", 1)
        if right.strip().isdigit():
            path_part = left
            line_num = int(right.strip())

    if line_num is None or line_num <= 0:
        return None

    path_s = path_part.strip()
    if not path_s:
        return None

    p = Path(path_s).expanduser()
    if not p.is_absolute():
        p = cwd / p
    path = str(p.resolve())
    spec = BreakpointSpec(path=path, line=line_num)
    return _apply_bp_opts(spec, opts)


def _apply_bp_opts(spec: BreakpointSpec, tokens: list[str]) -> BreakpointSpec | None:
    condition: str | None = spec.condition
    hit_condition: str | None = spec.hit_condition
    log_message: str | None = spec.log_message

    i = 0
    while i < len(tokens):
        tok = tokens[i]
        match tok:
            case "if" | "cond" | "condition":
                i += 1
                if i >= len(tokens):
                    return None
                condition = tokens[i]
            case "hit" | "hits" | "count":
                i += 1
                if i >= len(tokens):
                    return None
                hit_condition = tokens[i]
            case "log" | "print":
                i += 1
                if i >= len(tokens):
                    return None
                log_message = tokens[i]
            case _:
                if tok.startswith("if="):
                    condition = tok.removeprefix("if=") or None
                elif tok.startswith("hit="):
                    hit_condition = tok.removeprefix("hit=") or None
                elif tok.startswith("log="):
                    log_message = tok.removeprefix("log=") or None
                else:
                    return None
        i += 1

    return BreakpointSpec(
        path=spec.path,
        line=spec.line,
        condition=condition or None,
        hit_condition=hit_condition or None,
        log_message=log_message or None,
    )


def _bp_display_hint(bp: BreakpointInfo) -> str:
    parts: list[str] = []
    if bp.condition:
        parts.append(f"if {bp.condition}")
    if bp.hit_condition:
        parts.append(f"hit {bp.hit_condition}")
    if bp.log_message:
        parts.append("log")
    return "  •  ".join(parts)


class BreakpointDialog(ModalScreen[None]):
    BINDINGS: ClassVar[list[BindingType]] = [("escape", "app.pop_screen", "Close")]

    def __init__(self, *, ctx: AppContext) -> None:
        super().__init__()
        self._ctx = ctx
        self._task: asyncio.Task[None] | None = None

    def compose(self) -> ComposeResult:
        yield Container(
            Static("Add breakpoint", id="bp_title"),
            Input(
                placeholder="path:line  [if EXPR]  [hit N]  [log MSG]",
                id="bp_input",
            ),
            Static("Enter toggle / set config • Esc close", id="bp_hint"),
            id="bp_root",
        )

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    @on(Input.Submitted, "#bp_input")
    def _on_submit(self, event: Input.Submitted) -> None:
        store = self._ctx.services.get(SESSION_STORE)
        default_path = store.snapshot().source_path
        spec = parse_breakpoint_spec(event.value, default_path=default_path)
        if spec is None:
            hint = (
                "Invalid breakpoint. Use: path:line  [if EXPR]  [hit N]  [log MSG] "
                "(quote args with spaces)."
            )
            self.query_one("#bp_hint", Static).update(hint)
            return

        manager: SessionManager | None
        try:
            manager = self._ctx.services.get(SESSION_MANAGER)
        except KeyError:
            manager = None

        if manager is None:
            self._ctx.host.notify("No session backend available.", timeout=2.0)
            self.app.pop_screen()
            return

        has_config = any([spec.condition, spec.hit_condition, spec.log_message])
        action = "Configuring" if has_config else "Toggling"
        self._ctx.host.notify(
            f"{action} breakpoint: {Path(spec.path).name}:{spec.line}", timeout=2.0
        )

        async def _toggle_or_configure() -> None:
            try:
                if has_config and isinstance(manager, BreakpointConfigManager):
                    await manager.set_breakpoint_config(
                        spec.path,
                        spec.line,
                        condition=spec.condition,
                        hit_condition=spec.hit_condition,
                        log_message=spec.log_message,
                    )
                    return

                await manager.toggle_breakpoint(spec.path, spec.line)
            except Exception as exc:
                self._ctx.host.notify(str(exc), timeout=3.0)

        self._task = asyncio.create_task(_toggle_or_configure())
        self.app.pop_screen()


class BreakpointEditDialog(ModalScreen[None]):
    BINDINGS: ClassVar[list[BindingType]] = [("escape", "app.pop_screen", "Close")]

    def __init__(self, *, ctx: AppContext, breakpoint: BreakpointInfo) -> None:
        super().__init__()
        self._ctx = ctx
        self._bp = breakpoint
        self._task: asyncio.Task[None] | None = None

    def compose(self) -> ComposeResult:
        title = f"Breakpoint {Path(self._bp.path).name}:{self._bp.line}"
        yield Container(
            Static(title, id="bpedit_title"),
            Input(
                placeholder="condition (if …)",
                id="bpedit_condition",
                value=self._bp.condition or "",
            ),
            Input(
                placeholder="hit condition (e.g. 5 or >=5)",
                id="bpedit_hit",
                value=self._bp.hit_condition or "",
            ),
            Input(
                placeholder="log message (logpoint, optional)",
                id="bpedit_log",
                value=self._bp.log_message or "",
            ),
            Static("Enter save  •  Esc close  •  Empty clears", id="bpedit_hint"),
            id="bpedit_root",
        )

    def on_mount(self) -> None:
        self.styles.background = "transparent"
        self.query_one("#bpedit_condition", Input).focus()

    @on(Input.Submitted)
    def _on_submit(self, _event: Input.Submitted) -> None:
        manager: SessionManager | None
        try:
            manager = self._ctx.services.get(SESSION_MANAGER)
        except KeyError:
            manager = None

        if manager is None or not isinstance(manager, BreakpointConfigManager):
            self._ctx.host.notify("Breakpoint configuration is not supported.", timeout=2.5)
            self.app.pop_screen()
            return

        condition = self.query_one("#bpedit_condition", Input).value.strip() or None
        hit = self.query_one("#bpedit_hit", Input).value.strip() or None
        log = self.query_one("#bpedit_log", Input).value.strip() or None

        async def _apply() -> None:
            try:
                await manager.set_breakpoint_config(
                    self._bp.path,
                    self._bp.line,
                    condition=condition,
                    hit_condition=hit,
                    log_message=log,
                )
                hint = _bp_display_hint(
                    BreakpointInfo(
                        path=self._bp.path,
                        line=self._bp.line,
                        condition=condition,
                        hit_condition=hit,
                        log_message=log,
                    )
                )
                self._ctx.host.notify(
                    f"Updated breakpoint {Path(self._bp.path).name}:{self._bp.line} {hint}".strip(),
                    timeout=2.0,
                )
            except Exception as exc:
                self._ctx.host.notify(str(exc), timeout=3.0)

        self._task = asyncio.create_task(_apply())
        self.app.pop_screen()
