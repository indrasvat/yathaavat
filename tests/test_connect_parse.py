from __future__ import annotations

import time

from tests.support import make_context
from yathaavat.app.connect import (
    ConnectPicker,
    HostPort,
    _relative_time,
    parse_host_port,
)
from yathaavat.app.server_discovery import DiscoveredServer


def test_parse_host_port_parses_host_port() -> None:
    hp = parse_host_port("127.0.0.1:5678")
    assert hp is not None
    assert hp.host == "127.0.0.1"
    assert hp.port == 5678


def test_parse_host_port_allows_port_only() -> None:
    hp = parse_host_port("5678")
    assert hp is not None
    assert hp.host == "127.0.0.1"
    assert hp.port == 5678


def test_parse_host_port_rejects_invalid() -> None:
    assert parse_host_port("nope") is None
    assert parse_host_port("host:-1") is None
    assert parse_host_port("host:99999") is None


def test_parse_host_port_rejects_port_only_out_of_range() -> None:
    assert parse_host_port("-1") is None
    assert parse_host_port("0") is None
    assert parse_host_port("70000") is None
    assert parse_host_port("65536") is None


def test_connect_picker_builds_discovered_rows_and_filters_query() -> None:
    assert parse_host_port("5678") == HostPort(host="127.0.0.1", port=5678)
    assert parse_host_port("localhost:9999") == HostPort(host="localhost", port=9999)

    picker = ConnectPicker(ctx=make_context())
    picker._servers = [
        DiscoveredServer(host="127.0.0.1", port=5678, pid=10, process_name="api", alive=True)
    ]
    picker._entries = []

    rows = picker._build_rows("")
    assert rows[0].host == "127.0.0.1"
    assert rows[0].kind == "discovered"
    assert picker._build_rows("api")[0].port == 5678
    assert _relative_time(time.time() - 90) == "1m ago"
