from __future__ import annotations

import asyncio

import pytest

from yathaavat.core.dap.client import DapClient
from yathaavat.core.dap.codec import decode_message, encode_message, parse_content_length


async def _read_message(reader: asyncio.StreamReader) -> dict[str, object]:
    header = await reader.readuntil(b"\r\n\r\n")
    header = header[: -len(b"\r\n\r\n")]
    length = parse_content_length(header)
    body = await reader.readexactly(length)
    decoded = decode_message(body)
    assert isinstance(decoded, dict)
    return decoded


def test_event_handlers_may_issue_requests_without_deadlock() -> None:
    async def main() -> None:
        client: DapClient | None = None

        async def handle_conn(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            nonlocal client

            init_req = await _read_message(reader)
            assert init_req["type"] == "request"
            assert init_req["command"] == "initialize"

            writer.write(
                encode_message({"seq": 1, "type": "event", "event": "initialized", "body": {}})
            )
            await writer.drain()

            # The initialized handler should trigger another request.
            threads_req = await asyncio.wait_for(_read_message(reader), timeout=2.0)
            assert threads_req["type"] == "request"
            assert threads_req["command"] == "threads"

            writer.write(
                encode_message(
                    {
                        "seq": 2,
                        "type": "response",
                        "request_seq": threads_req["seq"],
                        "success": True,
                        "command": "threads",
                        "body": {"threads": []},
                    }
                )
            )
            await writer.drain()

            # Finally, respond to initialize.
            writer.write(
                encode_message(
                    {
                        "seq": 3,
                        "type": "response",
                        "request_seq": init_req["seq"],
                        "success": True,
                        "command": "initialize",
                        "body": {},
                    }
                )
            )
            await writer.drain()

            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(handle_conn, "127.0.0.1", 0)
        addr = server.sockets[0].getsockname()
        host, port = addr[0], addr[1]

        async with server:
            reader, writer = await asyncio.open_connection(host, port)
            client = DapClient(reader=reader, writer=writer)

            async def on_event(event: dict[str, object]) -> None:
                if event.get("event") != "initialized":
                    return
                assert client is not None
                await client.request("threads", {}, timeout_s=1.0)

            client.on_event(on_event)
            client.start()

            await client.request("initialize", {}, timeout_s=2.0)
            await client.close()

    asyncio.run(main())


def test_unknown_incoming_requests_are_rejected() -> None:
    async def main() -> None:
        async def handle_conn(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            # Send a request to the client (which it doesn't support).
            writer.write(
                encode_message(
                    {"seq": 99, "type": "request", "command": "reverseRequest", "arguments": {}}
                )
            )
            await writer.drain()

            # Client should reply with an error response.
            resp = await asyncio.wait_for(_read_message(reader), timeout=2.0)
            assert resp["type"] == "response"
            assert resp["request_seq"] == 99
            assert resp["success"] is False

            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(handle_conn, "127.0.0.1", 0)
        addr = server.sockets[0].getsockname()
        host, port = addr[0], addr[1]

        async with server:
            reader, writer = await asyncio.open_connection(host, port)
            client = DapClient(reader=reader, writer=writer)
            client.start()
            await asyncio.sleep(0.05)
            await client.close()

    asyncio.run(main())


def test_disconnect_handler_fires_on_remote_close() -> None:
    async def main() -> None:
        disconnected = asyncio.Event()

        async def handle_conn(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            # Read a request then close the transport without replying.
            msg = await _read_message(reader)
            assert msg["type"] == "request"
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(handle_conn, "127.0.0.1", 0)
        addr = server.sockets[0].getsockname()
        host, port = addr[0], addr[1]

        async with server:
            reader, writer = await asyncio.open_connection(host, port)
            client = DapClient(reader=reader, writer=writer)

            def on_disconnect(exc: BaseException) -> None:
                disconnected.set()

            client.on_disconnect(on_disconnect)
            client.start()

            with pytest.raises(ConnectionError):
                await client.request("initialize", {}, timeout_s=2.0)

            await asyncio.wait_for(disconnected.wait(), timeout=2.0)
            await client.close()

    asyncio.run(main())
