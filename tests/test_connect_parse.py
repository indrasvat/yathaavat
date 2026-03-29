from __future__ import annotations

from yathaavat.app.connect import parse_host_port


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
