from __future__ import annotations

from yathaavat.app.attach import _debugpy_dap_endpoint


def test_debugpy_dap_endpoint_parses_debugpy_adapter_args() -> None:
    args = (
        "/opt/homebrew/Cellar/python@3.14/3.14.2/Frameworks/Python.framework/Versions/3.14/"
        "Resources/Python.app/Contents/MacOS/Python "
        "-m debugpy --listen 127.0.0.1:51578 --wait-for-client -c 'print(1)'"
    )
    assert _debugpy_dap_endpoint(args) == ("127.0.0.1", 51578)


def test_debugpy_dap_endpoint_parses_port_only_form() -> None:
    args = "python -m debugpy --listen 5678 --wait-for-client -c 'print(1)'"
    assert _debugpy_dap_endpoint(args) == ("127.0.0.1", 5678)


def test_debugpy_dap_endpoint_ignores_non_adapter_processes() -> None:
    assert _debugpy_dap_endpoint("python -m http.server --port 8000") is None


def test_debugpy_dap_endpoint_ignores_debugpy_adapter_processes() -> None:
    args = "python -m debugpy.adapter --host 127.0.0.1 --port 51578 --for-server 51580"
    assert _debugpy_dap_endpoint(args) is None
