from __future__ import annotations

import argparse
import asyncio
from typing import Any, cast

from yathaavat.core import DapCapabilities, SessionState, SessionStore
from yathaavat.plugins.debugpy import DebugpySessionManager


class _BenchDap:
    def __init__(self, *, variable_count: int) -> None:
        self.variable_count = variable_count
        self.variable_requests: list[dict[str, object]] = []

    async def request(
        self,
        command: str,
        arguments: dict[str, object],
        timeout_s: float | None = None,
    ) -> dict[str, object]:
        _ = timeout_s
        if command == "scopes":
            return {
                "body": {
                    "scopes": [
                        {
                            "name": "Locals",
                            "variablesReference": 7,
                            "namedVariables": self.variable_count,
                        }
                    ]
                }
            }
        if command != "variables":
            return {"body": {}}

        self.variable_requests.append(dict(arguments))
        start_raw = arguments.get("start")
        count_raw = arguments.get("count")
        if isinstance(start_raw, int) and isinstance(count_raw, int):
            start = max(start_raw, 0)
            stop = min(start + max(count_raw, 0), self.variable_count)
        else:
            start = 0
            stop = self.variable_count

        return {
            "body": {
                "variables": [
                    {
                        "name": f"item_{idx}",
                        "value": str(idx),
                        "type": "int",
                        "variablesReference": 0,
                    }
                    for idx in range(start, stop)
                ]
            }
        }


async def _run(*, variable_count: int, iterations: int) -> None:
    store = SessionStore()
    manager = DebugpySessionManager(store=store, host=cast(Any, object()))
    dap = _BenchDap(variable_count=variable_count)
    cast(Any, manager)._dap = dap

    for frame_id in range(iterations):
        store.update(
            state=SessionState.PAUSED,
            selected_frame_id=frame_id,
            capabilities=DapCapabilities(supports_variable_paging=True),
        )
        await manager._refresh_locals(frame_id)

    snapshot = store.snapshot()
    last_request = dap.variable_requests[-1] if dap.variable_requests else {}
    print(
        "locals="
        f"{len(snapshot.locals)} requests={len(dap.variable_requests)} last_request={last_request}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variables", type=int, default=10_000)
    parser.add_argument("--iterations", type=int, default=25)
    args = parser.parse_args()
    asyncio.run(_run(variable_count=args.variables, iterations=args.iterations))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
