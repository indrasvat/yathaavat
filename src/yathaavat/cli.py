from __future__ import annotations

import argparse
from dataclasses import dataclass

from yathaavat import __version__
from yathaavat.app.tui import run_tui


@dataclass(frozen=True, slots=True)
class Args:
    command: str


def _parse_args(argv: list[str] | None) -> Args:
    parser = argparse.ArgumentParser(prog="yathaavat", add_help=True)
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "command",
        nargs="?",
        default="tui",
        choices=["tui"],
        help="Command to run (default: tui).",
    )
    ns = parser.parse_args(argv)
    return Args(command=ns.command)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    match args.command:
        case "tui":
            run_tui()
            return 0
        case _:
            raise AssertionError("unreachable")
