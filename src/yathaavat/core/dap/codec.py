from __future__ import annotations

import json


class DapCodecError(Exception):
    pass


def encode_message(message: object) -> bytes:
    body = json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    return header + body


def decode_message(data: bytes) -> object:
    try:
        return json.loads(data.decode("utf-8"))
    except Exception as exc:
        raise DapCodecError("Invalid DAP JSON body") from exc


def parse_content_length(header: bytes) -> int:
    try:
        text = header.decode("ascii")
    except UnicodeDecodeError as exc:
        raise DapCodecError("DAP header is not ASCII") from exc

    for line in text.split("\r\n"):
        if not line:
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        if key.strip().lower() != "content-length":
            continue
        try:
            length = int(value.strip())
        except ValueError as exc:
            raise DapCodecError("Invalid Content-Length value") from exc
        if length < 0:
            raise DapCodecError("Negative Content-Length")
        return length
    raise DapCodecError("Missing Content-Length header")
