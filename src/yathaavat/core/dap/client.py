from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from yathaavat.core.dap.codec import decode_message, encode_message, parse_content_length

type JsonObject = dict[str, object]
type EventHandler = Callable[[JsonObject], Awaitable[None] | None]


class DapRequestError(Exception):
    def __init__(self, *, command: str, message: str, response: JsonObject) -> None:
        super().__init__(f"{command}: {message}")
        self.command = command
        self.message = message
        self.response = response


@dataclass(slots=True)
class _Pending:
    command: str
    future: asyncio.Future[JsonObject]


class DapClient:
    def __init__(self, *, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._reader = reader
        self._writer = writer
        self._seq = 1
        self._pending: dict[int, _Pending] = {}
        self._event_handlers: list[EventHandler] = []
        self._event_queue: asyncio.Queue[JsonObject] = asyncio.Queue()
        self._listen_task: asyncio.Task[None] | None = None
        self._event_task: asyncio.Task[None] | None = None
        self._closed = False

    def on_event(self, handler: EventHandler) -> None:
        self._event_handlers.append(handler)

    def start(self) -> None:
        if self._listen_task is not None:
            return
        self._listen_task = asyncio.create_task(self._listen())
        self._event_task = asyncio.create_task(self._event_loop())

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._listen_task is not None:
            self._listen_task.cancel()
        if self._event_task is not None:
            self._event_task.cancel()
        self._writer.close()
        await self._writer.wait_closed()

        for pending in self._pending.values():
            if not pending.future.done():
                pending.future.cancel()
        self._pending.clear()

    async def request(
        self, command: str, arguments: JsonObject | None = None, *, timeout_s: float = 15.0
    ) -> JsonObject:
        seq = self._seq
        self._seq += 1
        request: JsonObject = {"seq": seq, "type": "request", "command": command}
        if arguments is not None:
            request["arguments"] = arguments

        loop = asyncio.get_running_loop()
        fut: asyncio.Future[JsonObject] = loop.create_future()
        self._pending[seq] = _Pending(command=command, future=fut)
        self._writer.write(encode_message(request))
        await self._writer.drain()

        try:
            response = await asyncio.wait_for(fut, timeout=timeout_s)
        except TimeoutError as exc:
            self._pending.pop(seq, None)
            raise TimeoutError(f"DAP request timed out: {command}") from exc

        if response.get("success") is False:
            msg = str(response.get("message") or "request failed")
            raise DapRequestError(command=command, message=msg, response=response)
        return response

    async def _listen(self) -> None:
        try:
            while True:
                msg = await _read_message(self._reader)
                await self._dispatch(msg)
        except asyncio.CancelledError:
            return
        except (asyncio.IncompleteReadError, ConnectionResetError):
            for pending in self._pending.values():
                if not pending.future.done():
                    pending.future.cancel()
            self._pending.clear()
            return
        except Exception:
            for pending in self._pending.values():
                if not pending.future.done():
                    pending.future.cancel()
            self._pending.clear()
            raise

    async def _dispatch(self, msg: JsonObject) -> None:
        match msg.get("type"):
            case "response":
                request_seq = msg.get("request_seq")
                if isinstance(request_seq, int) and request_seq in self._pending:
                    pending = self._pending.pop(request_seq)
                    if not pending.future.done():
                        pending.future.set_result(msg)
                return
            case "event":
                self._event_queue.put_nowait(msg)
                return
            case "request":
                await self._respond_unsupported(msg)
                return
            case _:
                return

    async def _respond_unsupported(self, request: JsonObject) -> None:
        request_seq = request.get("seq")
        command = request.get("command")
        if not isinstance(request_seq, int) or not isinstance(command, str):
            return
        response: JsonObject = {
            "type": "response",
            "seq": self._seq,
            "request_seq": request_seq,
            "success": False,
            "command": command,
            "message": "Unsupported DAP request",
        }
        self._seq += 1
        self._writer.write(encode_message(response))
        await self._writer.drain()

    async def _event_loop(self) -> None:
        try:
            while True:
                event = await self._event_queue.get()
                for handler in tuple(self._event_handlers):
                    result = handler(event)
                    if result is not None:
                        await result
        except asyncio.CancelledError:
            return


async def _read_message(reader: asyncio.StreamReader) -> JsonObject:
    header = await reader.readuntil(b"\r\n\r\n")
    header = header[: -len(b"\r\n\r\n")]
    content_length = parse_content_length(header)
    body = await reader.readexactly(content_length)
    decoded = decode_message(body)
    if not isinstance(decoded, dict):
        raise TypeError(f"DAP message must be an object, got {type(decoded)!r}")
    return decoded
