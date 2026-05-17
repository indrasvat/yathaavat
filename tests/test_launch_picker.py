from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest
from textual.widgets import Input, ListView

from tests.support import RecordingHost, RecordingManager, SingleScreenApp, make_context
from yathaavat.app.file_discovery import DiscoveredFile
from yathaavat.app.launch import LaunchPicker
from yathaavat.app.picker_history import HistoryEntry


def test_launch_picker_orders_history_and_boosted_files(tmp_path: Path) -> None:
    picker = LaunchPicker(ctx=make_context())
    picker._entries = [
        HistoryEntry("python old.py", "old", time.time() - 10),
    ]
    boosted = tmp_path / "main.py"
    normal = tmp_path / "tools" / "worker.py"
    picker._files = [
        DiscoveredFile(path=str(normal), boost=False),
        DiscoveredFile(path=str(boosted), boost=True),
    ]

    rows = picker._build_rows("")
    assert [(row.kind, row.command) for row in rows] == [
        ("history", "python old.py"),
        ("file", str(boosted)),
        ("file", str(normal)),
    ]
    assert [row.command for row in picker._build_rows("worker")] == [str(normal)]


def test_launch_picker_selected_file_quotes_path_and_launches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        monkeypatch.setattr(
            "yathaavat.app.picker_history.platformdirs.user_cache_dir",
            lambda _appname: str(tmp_path),
        )
        monkeypatch.setattr("yathaavat.app.launch.discover_python_files", lambda _root: [])
        host = RecordingHost()
        manager = RecordingManager()
        picker = LaunchPicker(ctx=make_context(host=host, manager=manager))
        script = tmp_path / "space dir" / "demo service.py"
        script.parent.mkdir()
        script.write_text("print('ok')\n", encoding="utf-8")

        async with SingleScreenApp(picker).run_test() as pilot:
            await pilot.pause()
            if picker._discover_task is not None:
                picker._discover_task.cancel()
            picker._loading = False
            picker._files = [DiscoveredFile(path=str(script), boost=True)]
            picker._refresh_results()
            lv = picker.query_one("#launch_list", ListView)
            lv.index = 0

            input_widget = picker.query_one("#launch_input", Input)
            picker._on_submit(Input.Submitted(input_widget, "demo"))
            await pilot.pause()

        assert ("launch", ((str(script),),)) in manager.calls
        assert host.notifications[-1][0].startswith("Launching")
        assert picker._history.load()[0].command == f"'{script}'"

    asyncio.run(run())


def test_launch_picker_manual_submit_reports_invalid_and_missing_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        monkeypatch.setattr(
            "yathaavat.app.picker_history.platformdirs.user_cache_dir",
            lambda _appname: str(tmp_path),
        )
        host = RecordingHost()
        picker = LaunchPicker(ctx=make_context(host=host))

        async with SingleScreenApp(picker).run_test() as pilot:
            await pilot.pause()
            if picker._discover_task is not None:
                picker._discover_task.cancel()
            picker._loading = False
            picker._refresh_results()
            lv = picker.query_one("#launch_list", ListView)
            lv.index = None
            input_widget = picker.query_one("#launch_input", Input)

            picker._on_submit(Input.Submitted(input_widget, "'unterminated"))
            picker._on_submit(Input.Submitted(input_widget, "python app.py"))
            await pilot.pause()

        assert host.notifications[0][0] == "Invalid command."
        assert host.notifications[1][0] == "No session backend available."

    asyncio.run(run())


def test_launch_picker_discovery_failure_clears_loading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        monkeypatch.chdir(tmp_path)

        def boom(_root: Path) -> list[DiscoveredFile]:
            raise OSError("nope")

        monkeypatch.setattr("yathaavat.app.launch.discover_python_files", boom)
        picker = LaunchPicker(ctx=make_context())
        monkeypatch.setattr(picker, "_refresh_results", lambda: None)
        await picker._discover_files()
        assert picker._files == []
        assert picker._loading is False

    asyncio.run(run())
