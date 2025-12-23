from __future__ import annotations

import asyncio
from typing import Any

import pytest

from yathaavat.app.attach import _list_listening_tcp_endpoints, _probe_dap_endpoint


def test_list_listening_tcp_endpoints_parses_lsof(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeCompleted:
        def __init__(self, stdout: str, returncode: int = 0) -> None:
            self.stdout = stdout
            self.returncode = returncode

    def fake_run(cmd: list[str], **kwargs: Any) -> FakeCompleted:
        assert cmd[:2] == ["lsof", "-nP"]
        out = (
            "COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME\n"
            "python3.14 123 robin 10u IPv4 0x0 0t0 TCP *:8000 (LISTEN)\n"
            "python3.14 123 robin 11u IPv6 0x0 0t0 TCP [::1]:5678 (LISTEN)\n"
            "python3.14 123 robin 12u IPv4 0x0 0t0 TCP 127.0.0.1:9898 (LISTEN)\n"
        )
        return FakeCompleted(out)

    monkeypatch.setattr("subprocess.run", fake_run)
    assert _list_listening_tcp_endpoints(123) == [
        ("127.0.0.1", 8000),
        ("::1", 5678),
        ("127.0.0.1", 9898),
    ]


def test_probe_dap_endpoint_accepts_dap_framing() -> None:
    async def main() -> None:
        async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            # Client writes a DAP request; we just respond with DAP framing.
            await reader.readuntil(b"\r\n\r\n")
            writer.write(b"Content-Length: 2\r\n\r\n{}")
            await writer.drain()
            writer.close()

        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        host, port = server.sockets[0].getsockname()[:2]
        assert host == "127.0.0.1"
        async with server:
            assert await _probe_dap_endpoint(host, int(port), timeout_s=0.5) is True

    asyncio.run(main())


def test_probe_dap_endpoint_rejects_http() -> None:
    async def main() -> None:
        async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            await reader.readuntil(b"\r\n\r\n")
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK")
            await writer.drain()
            writer.close()

        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        host, port = server.sockets[0].getsockname()[:2]
        async with server:
            assert await _probe_dap_endpoint(host, int(port), timeout_s=0.5) is False

    asyncio.run(main())
