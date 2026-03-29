from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CommandSpec:
    id: str
    title: str
    summary: str
    default_keys: tuple[str, ...] = ()


CommandHandler = Callable[[], Awaitable[None] | None]


@dataclass(frozen=True, slots=True)
class Command:
    spec: CommandSpec
    handler: CommandHandler

    async def run(self) -> None:
        result = self.handler()
        if result is None:
            return
        await result


class CommandRegistry:
    def __init__(self) -> None:
        self._commands: dict[str, Command] = {}

    def register(self, command: Command) -> None:
        if command.spec.id in self._commands:
            msg = f"Command already registered: {command.spec.id}"
            raise ValueError(msg)
        self._commands[command.spec.id] = command

    def get(self, command_id: str) -> Command:
        try:
            return self._commands[command_id]
        except KeyError as exc:
            raise KeyError(f"Unknown command: {command_id}") from exc

    def all(self) -> tuple[Command, ...]:
        return tuple(self._commands.values())
