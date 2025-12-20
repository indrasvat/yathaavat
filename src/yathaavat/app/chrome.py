from __future__ import annotations

from dataclasses import dataclass
from os import PathLike
from pathlib import Path

from rich.style import Style
from rich.text import Text
from textual.widgets import Static


@dataclass(frozen=True, slots=True)
class StatusSnapshot:
    workspace: str
    state: str
    pid: int | None
    python: str
    backend: str
    message: str = ""
    plugin_errors: int = 0


@dataclass(frozen=True, slots=True)
class PillStyle:
    fg: str
    bg: str
    bold: bool = False


class StatusLine(Static):
    def __init__(self) -> None:
        super().__init__("", id="status")

    def set(self, status: StatusSnapshot) -> None:
        text = Text()
        text.append_text(_pill("yathaavat", style=PillStyle(fg="#d6e2ff", bg="#101823", bold=True)))
        text.append(" ")

        if status.workspace:
            text.append_text(
                _pill(
                    _short_path(status.workspace),
                    style=PillStyle(fg="#d6e2ff", bg="#0e1521"),
                )
            )
            text.append(" ")

        text.append_text(_pill(status.state, style=_state_style(status.state)))

        if status.pid is not None:
            text.append(" ")
            text.append_text(
                _pill(f"PID {status.pid}", style=PillStyle(fg="#93a4c7", bg="#0e1521"))
            )

        if status.python:
            text.append(" ")
            text.append_text(
                _pill(f"Py {status.python}", style=PillStyle(fg="#93a4c7", bg="#0e1521"))
            )

        if status.backend:
            text.append(" ")
            text.append_text(_pill(status.backend, style=PillStyle(fg="#93a4c7", bg="#0e1521")))

        if status.plugin_errors:
            text.append(" ")
            text.append_text(
                _pill(
                    f"⚠ {status.plugin_errors} plugin",
                    style=PillStyle(fg="#FFD37C", bg="#21170e", bold=True),
                )
            )

        if status.message:
            text.append(" ")
            text.append(status.message, style=Style(color="#93a4c7"))

        self.update(text)


class HelpLine(Static):
    def __init__(self) -> None:
        super().__init__("", id="help")

    def set_text(self, text: str) -> None:
        self.update(text)


def _pill(label: str, *, style: PillStyle) -> Text:
    return Text(
        f" {label} ",
        style=Style(color=style.fg, bgcolor=style.bg, bold=style.bold),
    )


def _state_style(state: str) -> PillStyle:
    match state:
        case "PAUSED":
            return PillStyle(fg="#8bd5ff", bg="#0b1a2a", bold=True)
        case "RUNNING":
            return PillStyle(fg="#7CFFB2", bg="#0b2218", bold=True)
        case "DISCONNECTED":
            return PillStyle(fg="#FF7C9B", bg="#2a0e15", bold=True)
        case _:
            return PillStyle(fg="#93a4c7", bg="#101823", bold=True)


def _short_path(path: str | PathLike[str]) -> str:
    try:
        p = Path(path).expanduser()
    except TypeError:
        return str(path)

    home = Path.home()
    try:
        p = Path("~") / p.relative_to(home)
    except ValueError:
        pass

    s = str(p)
    if len(s) <= 44:
        return s
    return f"{s[:18]}…{s[-22:]}"
