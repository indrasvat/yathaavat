from __future__ import annotations

import asyncio
import socket

from yathaavat.app.server_discovery import probe_server


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_probe_open_port() -> None:
    """Probing a port with a real TCP listener returns True."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        result = asyncio.run(probe_server("127.0.0.1", port))
        assert result is True
    finally:
        srv.close()


def test_probe_closed_port() -> None:
    """Probing a port with no listener returns False."""
    port = _pick_free_port()
    result = asyncio.run(probe_server("127.0.0.1", port, timeout=0.1))
    assert result is False


def test_probe_timeout() -> None:
    """Probing with a very short timeout doesn't hang."""
    port = _pick_free_port()
    result = asyncio.run(probe_server("127.0.0.1", port, timeout=0.01))
    assert result is False
