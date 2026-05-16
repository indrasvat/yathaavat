from __future__ import annotations

from yathaavat.app.keys import format_key, format_keys


def test_key_formatting_normalises_common_terminal_names() -> None:
    assert format_key("ctrl+shift+f10") == "Ctrl+Shift+F10"
    assert format_key("option+escape") == "Alt+Esc"
    assert format_key("command+k") == "Meta+K"
    assert format_key(" ") == " "
    assert format_keys(("ctrl+k", "f5", "")) == "Ctrl+K / F5"
