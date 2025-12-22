from __future__ import annotations

from textual.binding import Binding

from yathaavat.app.panels import CodeView


def test_codeview_source_keybindings_override_textarea_defaults() -> None:
    expected = {
        "ctrl+f": "app.command('source.find')",
        "ctrl+g": "app.command('source.goto')",
        "enter": "app.command('debug.run_to_cursor')",
        "b": "app.command('breakpoint.toggle')",
        "y": "copy_selection",
    }

    actual: dict[str, str] = {}
    for binding in CodeView.BINDINGS:
        if isinstance(binding, Binding):
            actual[binding.key] = binding.action

    for key, action in expected.items():
        assert actual.get(key) == action
