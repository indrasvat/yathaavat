from __future__ import annotations

import asyncio
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, cast

import pytest
from textual.widgets import Static

from tests.support import RecordingHost, RecordingManager, SingleWidgetApp, make_context
from yathaavat import __version__
from yathaavat.app import attach
from yathaavat.app.chrome import (
    HelpLine,
    StatusLine,
    StatusSnapshot,
    _short_path,
    _state_style,
)
from yathaavat.app.connect import (
    ConnectPicker,
    HostPort,
    _relative_time as connect_relative_time,
    parse_host_port,
)
from yathaavat.app.host import TextualUiHost
from yathaavat.app.keys import format_key, format_keys
from yathaavat.app.launch import (
    LaunchPicker,
    _expand_tilde,
    _relative_time as launch_relative_time,
    parse_launch_spec,
)
from yathaavat.app.layout import _safe_dom_id
from yathaavat.app.palette import CommandPalette
from yathaavat.app.server_discovery import DiscoveredServer
from yathaavat.cli import _parse_args, main
from yathaavat.core import Command, CommandSpec, WidgetContribution
from yathaavat.core.processes import ProcessInfo
from yathaavat.core.widgets import Slot


def test_cli_parses_default_command_and_runs_tui(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[str] = []

    def fake_run_tui() -> None:
        called.append("run")

    monkeypatch.setattr("yathaavat.cli.run_tui", fake_run_tui)

    assert _parse_args([]).command == "tui"
    assert main(["tui"]) == 0
    assert called == ["run"]


def test_cli_version_flag_reports_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        _parse_args(["--version"])

    assert exc.value.code == 0
    assert f"yathaavat {__version__}" in capsys.readouterr().out


def test_textual_ui_host_noops_until_bound_and_delegates_after_bind() -> None:
    class FakeApp:
        def __init__(self) -> None:
            self.notifications: list[tuple[str, float]] = []
            self.later: list[object] = []
            self.screens: list[object] = []
            self.exited = False
            self.popped = 0

        def notify(self, message: str, *, timeout: float) -> None:
            self.notifications.append((message, timeout))

        def exit(self) -> None:
            self.exited = True

        def action_toggle_zoom(self) -> None:
            self.later.append("zoom")

        def action_open_source_find(self) -> None:
            self.later.append("find")

        def call_later(self, action: object) -> None:
            self.later.append(action)

        def push_screen(self, screen: object) -> None:
            self.screens.append(screen)

        def pop_screen(self) -> None:
            self.popped += 1

    host = TextualUiHost()
    host.notify("ignored")
    host.exit()

    app = FakeApp()
    assert host.bind(cast(Any, app)) is host
    host.notify("hello", timeout=2.0)
    host.toggle_zoom()
    host.open_source_find()
    host.push_screen(cast(Any, object()))
    host.pop_screen()
    host.exit()

    assert app.notifications == [("hello", 2.0)]
    assert len(app.later) == 2
    assert len(app.screens) == 1
    assert app.popped == 1
    assert app.exited is True


def test_key_formatting_normalises_common_terminal_names() -> None:
    assert format_key("ctrl+shift+f10") == "Ctrl+Shift+F10"
    assert format_key("option+escape") == "Alt+Esc"
    assert format_key("command+k") == "Meta+K"
    assert format_key(" ") == " "
    assert format_keys(("ctrl+k", "f5", "")) == "Ctrl+K / F5"


def test_status_line_renders_workspace_state_and_plugin_errors(tmp_path: Path) -> None:
    async def run() -> None:
        status = StatusLine()
        async with SingleWidgetApp(status).run_test() as pilot:
            await pilot.pause()
            status.set(
                StatusSnapshot(
                    workspace=str(tmp_path),
                    state="PAUSED",
                    pid=123,
                    python="3.14",
                    backend="debugpy",
                    zoom="Source",
                    message="ready",
                    plugin_errors=2,
                )
            )
            rendered = str(status.content)
            assert "yathaavat" in rendered
            assert "PAUSED" in rendered
            assert "PID 123" in rendered
            assert "ready" in rendered

        help_line = HelpLine()
        async with SingleWidgetApp(help_line).run_test() as pilot:
            await pilot.pause()
            help_line.set_text("F5 continue")
            assert str(help_line.content) == "F5 continue"

    asyncio.run(run())
    assert _state_style("RUNNING").bold is True
    assert _state_style("other").fg == "#93a4c7"
    assert _short_path(cast(Any, 123)) == "123"


def test_safe_dom_id_replaces_non_alphanumeric_chars() -> None:
    contribution = WidgetContribution(
        id="plugin.source/find",
        title="Find",
        slot=Slot.CENTER,
        factory=lambda _ctx: Static("x"),
    )
    assert _safe_dom_id(contribution) == "pane_plugin_source_find"


def test_command_palette_items_sort_and_fuzzy_filter() -> None:
    ctx = make_context()
    ctx.commands.register(
        Command(
            CommandSpec(
                id="debug.continue",
                title="Continue",
                summary="resume target",
                default_keys=("f5", "c"),
            ),
            handler=lambda: None,
        )
    )
    ctx.commands.register(
        Command(
            CommandSpec(id="source.find", title="Find", summary="search source"),
            handler=lambda: None,
        )
    )
    palette = CommandPalette(ctx=ctx)

    assert [item.title for item in palette._items()] == ["Continue", "Find"]
    palette.query_text = "src find"
    filtered = palette._items()
    assert [item.id for item in filtered] == ["source.find"]


def test_connect_parse_host_port_and_rows() -> None:
    assert parse_host_port("5678") == HostPort(host="127.0.0.1", port=5678)
    assert parse_host_port("0") is None
    assert parse_host_port("localhost:9999") == HostPort(host="localhost", port=9999)
    assert parse_host_port("bad") is None

    ctx = make_context()
    picker = ConnectPicker(ctx=ctx)
    picker._servers = [
        DiscoveredServer(host="127.0.0.1", port=5678, pid=10, process_name="api", alive=True)
    ]
    picker._entries = []
    rows = picker._build_rows("")
    assert rows[0].host == "127.0.0.1"
    assert rows[0].kind == "discovered"

    assert picker._build_rows("api")[0].port == 5678
    assert connect_relative_time(time.time() - 90) == "1m ago"


def test_launch_parse_expand_and_rows(tmp_path: Path) -> None:
    spec = parse_launch_spec("script.py --flag 'two words'")
    assert spec is not None
    assert spec.argv == [
        "script.py",
        "--flag",
        "two words",
    ]
    assert parse_launch_spec("") is None
    assert parse_launch_spec("'unterminated") is None

    home_script = Path.home() / "demo.py"
    expanded = _expand_tilde("~/demo.py --x")
    assert expanded.startswith(str(home_script))
    assert _expand_tilde("plain.py") == "plain.py"
    assert launch_relative_time(time.time() - 3700) == "1h ago"

    ctx = make_context()
    picker = LaunchPicker(ctx=ctx)
    picker._entries = []
    picker._files = []
    file_path = tmp_path / "demo.py"
    file_path.write_text("print('ok')\n", encoding="utf-8")
    from yathaavat.app.file_discovery import DiscoveredFile

    picker._files = [DiscoveredFile(path=str(file_path), boost=True)]
    rows = picker._build_rows("")
    assert rows[0].kind == "file"
    assert rows[0].command == str(file_path)


def test_attach_endpoint_parsers_and_safe_attach_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    assert attach._truncate("abcdef", 4) == "abc…"
    assert attach._debugpy_dap_endpoint("python -m debugpy --listen 5678 app.py") == (
        "127.0.0.1",
        5678,
    )
    assert attach._debugpy_dap_endpoint("debugpy --listen localhost:9000 app.py") == (
        "localhost",
        9000,
    )
    assert attach._debugpy_dap_endpoint("debugpy --listen bad") is None
    assert attach._debugpy_adapter_endpoint("python -m debugpy.adapter --host ::1 --port 4711") == (
        "::1",
        4711,
    )
    assert attach._debugpy_adapter_endpoint("python app.py") is None
    assert attach._is_loopback("[::1]") is True
    assert attach._is_loopback("10.0.0.2") is False

    monkeypatch.delattr(sys, "remote_exec", raising=False)
    assert attach._safe_attach_unavailable_reason() == "unsupported locally"
    monkeypatch.setattr(sys, "remote_exec", object(), raising=False)
    monkeypatch.setenv("PYTHON_DISABLE_REMOTE_DEBUG", "1")
    assert attach._safe_attach_unavailable_reason() == "disabled locally"


def test_attach_lsof_parsers_ignore_bad_process_output(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if "-sTCP:LISTEN" in cmd and "-t" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="101\nbad\n202\n", stderr="")
        if "-sTCP:LISTEN" in cmd:
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout=(
                    "COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME\n"
                    "python 1 me 3u IPv4 TCP *:5678 (LISTEN)\n"
                    "python 1 me 4u IPv6 TCP [::1]:9000 (LISTEN)\n"
                    "python 1 me 5u IPv4 TCP bad:port (LISTEN)\n"
                ),
                stderr="",
            )
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=(
                "python 1 me 3u IPv4 TCP 127.0.0.1:5000->127.0.0.1:6000 (ESTABLISHED)\n"
                "python 1 me 4u IPv4 TCP 127.0.0.1:5001->10.0.0.2:6001 (ESTABLISHED)\n"
                "python 1 me 5u IPv4 TCP bad\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert attach._list_listening_tcp_endpoints(123) == [("127.0.0.1", 5678), ("::1", 9000)]
    assert attach._list_established_remote_ports(123) == [6000]
    assert attach._listener_pids_for_port(6000) == [101, 202]


def test_attach_picker_rows_mark_debugpy_and_safe_attach_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(attach, "_safe_attach_unavailable_reason", lambda: None)
    ctx = make_context(manager=RecordingManager(), host=RecordingHost())
    picker = attach.AttachPicker(ctx=ctx)
    picker._processes = [
        ProcessInfo(
            pid=2, command="python", args="python -m debugpy --listen 5678 app.py", is_python=True
        ),
        ProcessInfo(
            pid=3,
            command="python3.14",
            args="python3.14 worker.py",
            is_python=True,
            python_version_hint="3.14",
        ),
        ProcessInfo(pid=4, command="node", args="node server.js", is_python=False),
    ]

    rows = picker._rows()
    assert [(row.pid, row.dap_endpoint, row.safe_attach_enabled) for row in rows] == [
        (2, ("127.0.0.1", 5678), False),
        (3, None, True),
    ]

    picker.show_non_python = True
    picker.query_text = "node"
    assert [row.pid for row in picker._rows()] == [4]
