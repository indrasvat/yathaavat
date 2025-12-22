from __future__ import annotations

from textual.binding import Binding

from yathaavat.app.panels import CodeView


def test_codeview_ctrl_f_opens_find() -> None:
    for binding in CodeView.BINDINGS:
        if isinstance(binding, Binding) and binding.key == "ctrl+f":
            assert binding.action == "app.command('source.find')"
            return

    raise AssertionError("CodeView is missing a ctrl+f binding for Source find.")
