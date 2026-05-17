from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest
from textual.widgets import Input, ListView, Static

from tests.support import RecordingHost, RecordingManager, SingleScreenApp, make_context
from yathaavat.app import attach
from yathaavat.core.processes import PROCESS_DISCOVERY, ProcessInfo


@dataclass(slots=True)
class _Discovery:
    processes: list[ProcessInfo]

    def list_processes(self) -> list[ProcessInfo]:
        return self.processes


def test_attach_picker_loads_processes_from_registered_discovery() -> None:
    async def run() -> None:
        ctx = make_context(manager=RecordingManager())
        ctx.services.register(
            PROCESS_DISCOVERY,
            _Discovery(
                [ProcessInfo(pid=11, command="python", args="python app.py", is_python=True)]
            ),
        )
        picker = attach.AttachPicker(ctx=ctx)

        async with SingleScreenApp(picker).run_test() as pilot:
            await pilot.pause()
            if picker._load_task is not None:
                await picker._load_task
            assert picker._loading is False
            assert "1 found" in str(picker.query_one("#attach_title", Static).content)
            assert len(picker.query_one(ListView).children) == 1

    asyncio.run(run())


def test_attach_picker_reports_missing_discovery_service() -> None:
    async def run() -> None:
        picker = attach.AttachPicker(ctx=make_context())

        async with SingleScreenApp(picker).run_test() as pilot:
            await pilot.pause()
            if picker._load_task is not None:
                await picker._load_task
            assert picker._processes == []
            assert "no discovery service" in str(picker.query_one("#attach_title", Static).content)
            empty = picker.query_one(ListView).children[0].query_one(Static)
            assert "No processes found" in str(empty.content)

    asyncio.run(run())


def test_attach_picker_submit_prefers_exact_pid_from_filtered_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        host = RecordingHost()
        manager = RecordingManager()
        picker = attach.AttachPicker(ctx=make_context(host=host, manager=manager))
        monkeypatch.setattr(attach, "_infer_debugpy_dap_endpoint", _return_no_endpoint)

        async with SingleScreenApp(picker).run_test() as pilot:
            await pilot.pause()
            if picker._load_task is not None:
                picker._load_task.cancel()
            picker._processes = [
                ProcessInfo(pid=20, command="python", args="python api.py", is_python=True),
                ProcessInfo(pid=21, command="python", args="python worker.py", is_python=True),
            ]
            picker._loading = False
            picker._refresh_results()
            input_widget = picker.query_one("#attach_input", Input)
            picker._on_submit(Input.Submitted(input_widget, "21"))
            await pilot.pause()

        assert ("attach", (21,)) in manager.calls

    asyncio.run(run())


def test_attach_picker_connects_to_inferred_dap_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        host = RecordingHost()
        manager = RecordingManager()
        picker = attach.AttachPicker(ctx=make_context(host=host, manager=manager))

        async def infer(pid: int) -> tuple[str, int] | None:
            assert pid == 44
            return "127.0.0.1", 9000

        monkeypatch.setattr(attach, "_infer_debugpy_dap_endpoint", infer)
        async with SingleScreenApp(picker).run_test() as pilot:
            await pilot.pause()
            if picker._load_task is not None:
                picker._load_task.cancel()
            picker._start_attach(
                pid=44,
                dap_endpoint=None,
                safe_attach_candidate=False,
                safe_attach_enabled=False,
                safe_attach_blocked_reason=None,
            )
            if picker._attach_task is not None:
                await picker._attach_task

        assert ("connect", ("127.0.0.1", 9000)) in manager.calls
        assert any("Found debugpy" in message for message, _timeout in host.notifications)

    asyncio.run(run())


def test_attach_picker_uses_explicit_dap_endpoint_and_validates_shape() -> None:
    async def run() -> None:
        host = RecordingHost()
        manager = RecordingManager()
        picker = attach.AttachPicker(ctx=make_context(host=host, manager=manager))

        async with SingleScreenApp(picker).run_test() as pilot:
            await pilot.pause()
            if picker._load_task is not None:
                picker._load_task.cancel()
            picker._start_attach(
                pid=55,
                dap_endpoint=("localhost", 5678),
                safe_attach_candidate=False,
                safe_attach_enabled=False,
                safe_attach_blocked_reason=None,
            )
            if picker._attach_task is not None:
                await picker._attach_task

        assert ("connect", ("localhost", 5678)) in manager.calls
        assert host.notifications[-1][0].startswith("Connecting to localhost:5678")

    asyncio.run(run())


async def _return_no_endpoint(_pid: int) -> tuple[str, int] | None:
    return None


def test_attach_picker_safe_attach_and_fallback_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        host = RecordingHost()
        manager = RecordingManager()
        picker = attach.AttachPicker(ctx=make_context(host=host, manager=manager))
        monkeypatch.setattr(attach, "_infer_debugpy_dap_endpoint", _return_no_endpoint)

        async with SingleScreenApp(picker).run_test() as pilot:
            await pilot.pause()
            if picker._load_task is not None:
                picker._load_task.cancel()
            picker._start_attach(
                pid=77,
                dap_endpoint=None,
                safe_attach_candidate=True,
                safe_attach_enabled=True,
                safe_attach_blocked_reason=None,
            )
            if picker._attach_task is not None:
                await picker._attach_task

        assert ("safe_attach", (77,)) in manager.calls

        host2 = RecordingHost()
        manager2 = RecordingManager()
        picker2 = attach.AttachPicker(ctx=make_context(host=host2, manager=manager2))
        async with SingleScreenApp(picker2).run_test() as pilot:
            await pilot.pause()
            if picker2._load_task is not None:
                picker2._load_task.cancel()
            picker2._start_attach(
                pid=88,
                dap_endpoint=None,
                safe_attach_candidate=True,
                safe_attach_enabled=False,
                safe_attach_blocked_reason="disabled by target",
            )
            if picker2._attach_task is not None:
                await picker2._attach_task

        assert ("attach", (88,)) in manager2.calls
        assert any("disabled by target" in message for message, _timeout in host2.notifications)

    asyncio.run(run())


def test_attach_picker_prototype_notifications_without_manager() -> None:
    async def run() -> None:
        host = RecordingHost()
        picker = attach.AttachPicker(ctx=make_context(host=host))

        async with SingleScreenApp(picker).run_test() as pilot:
            await pilot.pause()
            if picker._load_task is not None:
                picker._load_task.cancel()
            picker._start_attach(
                pid=99,
                dap_endpoint=("127.0.0.1", 6000),
                safe_attach_candidate=False,
                safe_attach_enabled=False,
                safe_attach_blocked_reason=None,
            )
            await pilot.pause()

        assert host.notifications == [("connect to 127.0.0.1:6000 (prototype)", 1.2)]

    asyncio.run(run())
