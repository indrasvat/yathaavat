from __future__ import annotations

from yathaavat.plugins.processes import parse_ps_output


def test_parse_ps_output_flags_python_processes() -> None:
    out = parse_ps_output(
        "  123 python3.14 python3.14 -m myapp\n"
        "  124 bash bash -lc echo hi\n"
        "  125 Python Python -c print('x')\n"
        "  126 /opt/homebrew/Ce /opt/homebrew/Cellar/python@3.14/3.14.2/bin/python3.14 -c 1\n"
    )
    by_pid = {p.pid: p for p in out}
    assert by_pid[123].is_python is True
    assert by_pid[124].is_python is False
    assert by_pid[125].is_python is True
    assert by_pid[126].is_python is True


def test_parse_ps_output_extracts_version_hint() -> None:
    out = parse_ps_output("  123 python3.14 python3.14 -m myapp\n")
    assert out[0].python_version_hint == "3.14"

    out = parse_ps_output(
        "  126 /opt/homebrew/Ce /opt/homebrew/Cellar/python@3.14/3.14.2/bin/python3.14 -c 1\n"
    )
    assert out[0].python_version_hint == "3.14"


def test_parse_ps_output_uses_args_argv0_for_display_command() -> None:
    out = parse_ps_output(
        "  126 /opt/homebrew/Ce /opt/homebrew/Cellar/python@3.14/3.14.2/bin/python3.14 -c 1\n"
    )
    assert out[0].command == "python3.14"
