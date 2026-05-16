from __future__ import annotations

import pytest

from yathaavat import __version__
from yathaavat.cli import _parse_args, main


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
