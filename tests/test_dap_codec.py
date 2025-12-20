from __future__ import annotations

import pytest

from yathaavat.core.dap.codec import DapCodecError, encode_message, parse_content_length


def test_encode_message_sets_correct_content_length() -> None:
    data = encode_message({"seq": 1, "type": "request", "command": "initialize"})
    header, body = data.split(b"\r\n\r\n", 1)
    assert parse_content_length(header) == len(body)


def test_parse_content_length_errors_on_missing() -> None:
    with pytest.raises(DapCodecError, match="Missing Content-Length"):
        parse_content_length(b"Foo: 1\r\nBar: 2")
