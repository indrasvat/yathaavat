from __future__ import annotations

import asyncio
from typing import cast

from textual import events
from textual.widgets import ListView

from tests.support import RecordingManager, SingleWidgetApp, make_context
from yathaavat.app.expression import ExpressionInput
from yathaavat.app.input_history import InputHistory
from yathaavat.core import CompletionItem


def test_expression_input_requests_accepts_and_closes_completions() -> None:
    async def run() -> None:
        manager = RecordingManager(
            completions=(
                CompletionItem(
                    label="subtotal",
                    insert_text="subtotal",
                    replace_start=len("order."),
                    replace_length=len("subt"),
                    type="property",
                ),
                CompletionItem(
                    label="summary",
                    insert_text="summary",
                    replace_start=len("order."),
                    replace_length=len("subt"),
                    type="property",
                ),
            )
        )
        ctx = make_context(manager=manager)
        app = SingleWidgetApp(lambda: ExpressionInput(ctx=ctx, placeholder="expr"))

        async with app.run_test() as pilot:
            await pilot.pause()
            expr = cast(ExpressionInput, app.widget)
            expr.value = "order.subt"
            expr.request_completions()
            await pilot.pause()

            completions = expr.query_one(ListView)
            assert completions.styles.display == "block"
            assert len(completions.children) == 2
            assert manager.calls == [("complete", ("order.subt", len("order.subt")))]

            expr.completion_next()
            assert expr.accept_completion() is True
            assert expr.value == "order.summary"
            assert completions.styles.display == "none"
            assert expr.accept_completion() is False

    asyncio.run(run())


def test_expression_input_history_submit_and_key_bindings() -> None:
    async def run() -> None:
        history = InputHistory()
        history.push("oldest()")
        history.push("newest()")
        manager = RecordingManager(
            completions=(
                CompletionItem(
                    label="value", insert_text="value", replace_start=0, replace_length=3
                ),
            )
        )
        expr = ExpressionInput(ctx=make_context(manager=manager), history=history)

        async with SingleWidgetApp(expr).run_test() as pilot:
            await pilot.pause()
            expr.value = "scratch"
            expr.history_prev()
            assert expr.value == "newest()"
            expr.history_prev()
            assert expr.value == "oldest()"
            expr.history_next()
            assert expr.value == "newest()"
            expr.history_next()
            assert expr.value == "scratch"

            expr.value = "abc"
            await expr._area.on_key(events.Key("tab", "\t"))
            await pilot.pause()
            assert expr.query_one(ListView).styles.display == "block"

            await expr._area.on_key(events.Key("enter", "\n"))
            assert expr.value == "value"
            assert expr.query_one(ListView).styles.display == "none"

            expr.submit()
            assert history.items()[-1] == "value"

            expr.value = "abc"
            expr._show_completions(
                (
                    CompletionItem(
                        label="abcd",
                        insert_text="abcd",
                        replace_start=0,
                        replace_length=3,
                    ),
                )
            )
            await expr._area.on_key(events.Key("escape", None))
            assert expr.query_one(ListView).styles.display == "none"

            expr.clear()
            assert expr.value == ""

    asyncio.run(run())


def test_expression_input_without_completion_backend_hides_stale_menu() -> None:
    async def run() -> None:
        expr = ExpressionInput(ctx=make_context())
        async with SingleWidgetApp(expr).run_test() as pilot:
            await pilot.pause()
            expr._show_completions(
                (CompletionItem(label="x", insert_text="x", replace_start=0, replace_length=0),)
            )
            assert expr.query_one(ListView).styles.display == "block"
            expr.request_completions()
            assert expr.query_one(ListView).styles.display == "none"

    asyncio.run(run())
