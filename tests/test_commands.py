from __future__ import annotations

import pytest

from yathaavat.core.commands import Command, CommandRegistry, CommandSpec


def test_register_and_get_command() -> None:
    reg = CommandRegistry()
    cmd = Command(CommandSpec(id="x", title="X", summary="x"), handler=lambda: None)
    reg.register(cmd)
    assert reg.get("x").spec.title == "X"


def test_register_duplicate_command_raises() -> None:
    reg = CommandRegistry()
    cmd = Command(CommandSpec(id="x", title="X", summary="x"), handler=lambda: None)
    reg.register(cmd)
    with pytest.raises(ValueError, match="already registered"):
        reg.register(cmd)


def test_get_unknown_command_raises_keyerror() -> None:
    reg = CommandRegistry()
    with pytest.raises(KeyError, match="Unknown command"):
        reg.get("nope")
