from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest
from textual.widgets import Input, ListView

from tests.support import RecordingHost, RecordingManager, SingleScreenApp, make_context
from yathaavat.app.connect import ConnectPicker
from yathaavat.app.picker_history import HistoryEntry
from yathaavat.app.server_discovery import DiscoveredServer


def test_connect_picker_builds_deduplicated_discovery_and_history_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "yathaavat.app.picker_history.platformdirs.user_cache_dir",
        lambda _appname: str(tmp_path),
    )
    picker = ConnectPicker(ctx=make_context())
    picker._servers = [
        DiscoveredServer("127.0.0.1", 5678, 100, "api.py", True),
    ]
    picker._entries = [
        HistoryEntry("127.0.0.1:5678", "duplicate", time.time()),
        HistoryEntry("localhost:6000", "worker", time.time() - 3600),
        HistoryEntry("not an endpoint", "bad", time.time()),
    ]
    picker._liveness = {("localhost", 6000): True}

    rows = picker._build_rows("")
    assert [(row.host, row.port, row.kind) for row in rows] == [
        ("127.0.0.1", 5678, "discovered"),
        ("localhost", 6000, "history"),
    ]

    assert [(row.host, row.port) for row in picker._build_rows("worker")] == [
        ("localhost", 6000),
    ]


def test_connect_picker_submit_selected_row_connects_and_records_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        monkeypatch.setattr(
            "yathaavat.app.picker_history.platformdirs.user_cache_dir",
            lambda _appname: str(tmp_path),
        )
        host = RecordingHost()
        manager = RecordingManager()
        picker = ConnectPicker(ctx=make_context(host=host, manager=manager))

        async with SingleScreenApp(picker).run_test() as pilot:
            await pilot.pause()
            if picker._discover_task is not None:
                picker._discover_task.cancel()
            picker._loading = False
            picker._servers = [DiscoveredServer("127.0.0.1", 5678, 42, "svc.py", True)]
            picker._refresh_results()

            lv = picker.query_one("#connect_list", ListView)
            lv.index = 0
            input_widget = picker.query_one("#connect_input", Input)
            picker._on_submit(Input.Submitted(input_widget, "svc"))
            await pilot.pause()

        assert ("connect", ("127.0.0.1", 5678)) in manager.calls
        assert host.notifications[-1][0].startswith("Connecting to 127.0.0.1:5678")
        assert picker._history.load()[0].command == "127.0.0.1:5678"

    asyncio.run(run())


def test_connect_picker_manual_submit_handles_invalid_and_missing_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        monkeypatch.setattr(
            "yathaavat.app.picker_history.platformdirs.user_cache_dir",
            lambda _appname: str(tmp_path),
        )
        host = RecordingHost()
        picker = ConnectPicker(ctx=make_context(host=host))

        async with SingleScreenApp(picker).run_test() as pilot:
            await pilot.pause()
            if picker._discover_task is not None:
                picker._discover_task.cancel()
            picker._loading = False
            picker._refresh_results()
            lv = picker.query_one("#connect_list", ListView)
            lv.index = None
            input_widget = picker.query_one("#connect_input", Input)

            picker._on_submit(Input.Submitted(input_widget, "bad endpoint"))
            picker._on_submit(Input.Submitted(input_widget, "localhost:6000"))
            await pilot.pause()

        assert host.notifications[0][0] == "Invalid host:port."
        assert host.notifications[1][0] == "No session backend available."

    asyncio.run(run())


def test_connect_picker_discovery_and_history_probe_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        monkeypatch.setattr(
            "yathaavat.app.picker_history.platformdirs.user_cache_dir",
            lambda _appname: str(tmp_path),
        )

        async def fake_discover() -> list[DiscoveredServer]:
            return [DiscoveredServer("127.0.0.1", 7000, None, "server", True)]

        async def fake_probe(entries: list[tuple[str, int]]) -> dict[tuple[str, int], bool]:
            return {entry: entry[1] == 6000 for entry in entries}

        monkeypatch.setattr("yathaavat.app.connect.discover_debugpy_servers", fake_discover)
        monkeypatch.setattr("yathaavat.app.connect.probe_history_entries", fake_probe)

        picker = ConnectPicker(ctx=make_context())
        picker._entries = [
            HistoryEntry("localhost:6000", "ok", time.time()),
            HistoryEntry("bad", "bad", time.time()),
        ]
        monkeypatch.setattr(picker, "_refresh_results", lambda: None)

        assert await picker._probe_history() == {("localhost", 6000): True}
        await picker._discover()
        assert [srv.port for srv in picker._servers] == [7000]
        assert picker._liveness == {("localhost", 6000): True}
        assert picker._loading is False

    asyncio.run(run())
