from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata
from typing import Any

import pytest

from yathaavat.core import (
    AppContext,
    CommandRegistry,
    NullUiHost,
    Plugin,
    PluginManager,
    ServiceRegistry,
    Slot,
    WidgetRegistry,
)


def test_load_plugins_does_not_crash() -> None:
    pm = PluginManager()
    plugins, errors = pm.load()
    # At minimum, builtin plugin should be discoverable when running in an installed env.
    # In non-installed contexts, this may be empty; the invariant is: no crashes.
    assert isinstance(plugins, list)
    assert isinstance(errors, list)


def test_plugin_manager_sorts_plugins_and_isolates_bad_entry_points(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @dataclass(frozen=True, slots=True)
    class NamedPlugin(Plugin):
        name: str

        @property
        def id(self) -> str:
            return self.name

        def register(self, _ctx: AppContext) -> None:
            return None

    @dataclass(frozen=True, slots=True)
    class FakeEntryPoint:
        name: str
        loaded: Any

        def load(self) -> Any:
            return self.loaded

    def make_beta() -> Plugin:
        return NamedPlugin("beta")

    monkeypatch.setattr(
        metadata,
        "entry_points",
        lambda *, group: [
            FakeEntryPoint("zeta", NamedPlugin("zeta")),
            FakeEntryPoint("beta", make_beta),
            FakeEntryPoint("bad", object()),
        ],
    )

    plugins, errors = PluginManager(group="demo.plugins").load()

    assert [plugin.id for plugin in plugins] == ["beta", "zeta"]
    assert [error.plugin_name for error in errors] == ["bad"]
    assert "did not return a Plugin" in str(errors[0].error)


def test_builtin_plugin_registers_some_contributions() -> None:
    commands = CommandRegistry()
    widgets = WidgetRegistry()
    ctx = AppContext(
        commands=commands,
        widgets=widgets,
        services=ServiceRegistry(),
        host=NullUiHost(),
    )

    from yathaavat.plugins.builtin import plugin

    plugin().register(ctx)
    assert commands.get("app.quit").spec.title == "Quit"
    assert widgets.contributions_for(Slot.LEFT)
