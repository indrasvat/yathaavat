from __future__ import annotations

import pytest

from yathaavat.core.dap.codec import (
    DapCodecError,
    decode_message,
    encode_message,
    parse_content_length,
)


def test_encode_message_sets_correct_content_length() -> None:
    data = encode_message({"seq": 1, "type": "request", "command": "initialize"})
    header, body = data.split(b"\r\n\r\n", 1)
    assert parse_content_length(header) == len(body)
    assert decode_message(body) == {"seq": 1, "type": "request", "command": "initialize"}


def test_encode_message_preserves_utf8_body_length() -> None:
    data = encode_message({"message": "नमस्ते"})
    header, body = data.split(b"\r\n\r\n", 1)

    assert parse_content_length(header) == len(body)
    assert decode_message(body) == {"message": "नमस्ते"}


def test_parse_content_length_errors_on_missing() -> None:
    with pytest.raises(DapCodecError, match="Missing Content-Length"):
        parse_content_length(b"Foo: 1\r\nBar: 2")


@pytest.mark.parametrize(
    ("header", "message"),
    [
        (b"Content-Length: nope", "Invalid Content-Length value"),
        (b"Content-Length: -1", "Negative Content-Length"),
        ("Content-Length: 1\nश".encode(), "DAP header is not ASCII"),
    ],
)
def test_parse_content_length_rejects_bad_headers(header: bytes, message: str) -> None:
    with pytest.raises(DapCodecError, match=message):
        parse_content_length(header)


def test_parse_content_length_ignores_unknown_and_malformed_header_lines() -> None:
    assert parse_content_length(b"Bad-Line\r\nX-Trace: 1\r\ncontent-length: 7") == 7


def test_decode_message_reports_invalid_json_body() -> None:
    with pytest.raises(DapCodecError, match="Invalid DAP JSON body"):
        decode_message(b"{")
