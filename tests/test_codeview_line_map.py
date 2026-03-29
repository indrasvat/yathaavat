from __future__ import annotations

from yathaavat.app.panels import CodeView


def test_codeview_line_number_at_viewport_y_maps_to_document_lines() -> None:
    view = CodeView()
    view.text = "a\nb\nc"

    assert view.line_number_at_viewport_y(0) == 1
    assert view.line_number_at_viewport_y(1) == 2
    assert view.line_number_at_viewport_y(2) == 3
    assert view.line_number_at_viewport_y(3) is None
