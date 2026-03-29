from __future__ import annotations

from yathaavat.core import (
    AppContext,
    CommandRegistry,
    NullUiHost,
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
