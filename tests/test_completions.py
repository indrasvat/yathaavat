from __future__ import annotations

from yathaavat.app.expression import apply_completion
from yathaavat.core import CompletionItem
from yathaavat.plugins.debugpy import _infer_completion_span, _parse_completion_targets


def test_infer_completion_span_replaces_identifier_suffix() -> None:
    text = "order.subt"
    cursor = len(text)
    assert _infer_completion_span(text, cursor) == (len("order."), len("subt"))


def test_parse_completion_targets_prefers_adapter_range() -> None:
    text = "order.subt"
    resp: dict[str, object] = {
        "body": {
            "targets": [
                {"label": "subtotal", "text": "subtotal", "start": 6, "length": 4, "type": "prop"}
            ]
        }
    }
    items = _parse_completion_targets(resp, text=text, cursor=len(text))
    assert items == (
        CompletionItem(
            label="subtotal",
            insert_text="subtotal",
            replace_start=6,
            replace_length=4,
            type="prop",
        ),
    )


def test_parse_completion_targets_falls_back_to_inferred_span() -> None:
    text = "order.subt"
    resp: dict[str, object] = {"body": {"targets": [{"label": "subtotal"}]}}
    items = _parse_completion_targets(resp, text=text, cursor=len(text))
    assert items[0].replace_start == len("order.")
    assert items[0].replace_length == len("subt")


def test_parse_completion_targets_invalid_range_uses_fallback() -> None:
    text = "order.subt"
    resp: dict[str, object] = {
        "body": {"targets": [{"label": "subtotal", "start": 999, "length": 1}]}
    }
    items = _parse_completion_targets(resp, text=text, cursor=len(text))
    assert items[0].replace_start == len("order.")
    assert items[0].replace_length == len("subt")


def test_parse_completion_targets_sorts_by_label() -> None:
    resp: dict[str, object] = {"body": {"targets": [{"label": "b"}, {"label": "a"}]}}
    items = _parse_completion_targets(resp, text="a", cursor=1)
    assert [it.label for it in items] == ["a", "b"]


def test_parse_completion_targets_filters_dunders_by_default() -> None:
    resp: dict[str, object] = {
        "body": {"targets": [{"label": "__class__"}, {"label": "alpha"}, {"label": "__dict__"}]}
    }
    items = _parse_completion_targets(resp, text="obj.", cursor=len("obj."))
    assert [it.label for it in items] == ["alpha"]


def test_parse_completion_targets_keeps_dunders_when_prefix_starts_underscore() -> None:
    resp: dict[str, object] = {"body": {"targets": [{"label": "__class__"}, {"label": "__dict__"}]}}
    items = _parse_completion_targets(resp, text="obj.__", cursor=len("obj.__"))
    assert [it.label for it in items] == ["__class__", "__dict__"]


def test_apply_completion_replaces_span_and_moves_cursor() -> None:
    item = CompletionItem(
        label="subtotal",
        insert_text="subtotal",
        replace_start=len("order."),
        replace_length=len("subt"),
    )
    text, cursor = apply_completion("order.subt", item)
    assert text == "order.subtotal"
    assert cursor == len("order.subtotal")


def test_apply_completion_clamps_out_of_bounds_ranges() -> None:
    item = CompletionItem(label="x", insert_text="x", replace_start=999, replace_length=10)
    text, cursor = apply_completion("abc", item)
    assert text == "abcx"
    assert cursor == len("abcx")
