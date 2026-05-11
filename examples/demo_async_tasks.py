# /// script
# requires-python = ">=3.14"
# dependencies = [
#   "debugpy",
# ]
# ///
"""Async demo target with a rich task graph for exercising the Tasks panel.

Run under yathaavat via Connect (Ctrl+K):

    uv run --python python3.14 examples/demo_async_tasks.py

The script starts a debugpy listener on 127.0.0.1:5678 and then runs
`main()` which spawns several named tasks that:
  - await each other in a linear chain (producer -> transformer -> consumer)
  - fan out via asyncio.gather into parallel worker tasks
  - sit idle in `asyncio.sleep()` for a long time (pending forever)
  - hit a breakpoint inside an async function so the Tasks panel can
    render a pause-time snapshot with rich state.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import debugpy


async def producer(queue: asyncio.Queue[int], count: int) -> None:
    for i in range(count):
        await asyncio.sleep(0.05)
        await queue.put(i)
    await queue.put(-1)


async def transformer(src: asyncio.Queue[int], dst: asyncio.Queue[int]) -> None:
    while True:
        value = await src.get()
        if value == -1:
            await dst.put(-1)
            return
        await asyncio.sleep(0.02)
        await dst.put(value * value)


async def consumer(queue: asyncio.Queue[int], out: list[int]) -> None:
    while True:
        value = await queue.get()
        if value == -1:
            return
        out.append(value)


async def worker(name: str, delay: float) -> str:
    await asyncio.sleep(delay)
    return f"{name}:done"


async def idle_forever(label: str) -> None:
    await asyncio.sleep(3600)


async def hit_breakpoint(depth: int) -> int:
    if depth <= 0:
        # This is the line we want the debugger to pause on so that
        # the Tasks panel can snapshot the full live task graph.
        debugpy.breakpoint()
        here = sys._getframe().f_lineno
        return here
    return await hit_breakpoint(depth - 1)


async def run_pipeline() -> list[int]:
    src: asyncio.Queue[int] = asyncio.Queue()
    dst: asyncio.Queue[int] = asyncio.Queue()
    out: list[int] = []
    async with asyncio.TaskGroup() as tg:
        tg.create_task(producer(src, count=5), name="pipeline.producer")
        tg.create_task(transformer(src, dst), name="pipeline.transformer")
        tg.create_task(consumer(dst, out), name="pipeline.consumer")
    return out


async def run_workers() -> list[str]:
    return await asyncio.gather(
        worker("fast", 0.05),
        worker("medium", 0.15),
        worker("slow", 0.35),
    )


async def main() -> None:
    idle_a = asyncio.create_task(idle_forever("idle-a"), name="idle.a")
    idle_b = asyncio.create_task(idle_forever("idle-b"), name="idle.b")

    pipeline_task = asyncio.create_task(run_pipeline(), name="pipeline.root")
    workers_task = asyncio.create_task(run_workers(), name="workers.root")

    # Let everything settle into its suspended state.
    await asyncio.sleep(0.2)

    # This call is the designated pause point.
    _ = await hit_breakpoint(3)

    await pipeline_task
    await workers_task
    idle_a.cancel()
    idle_b.cancel()


def enable_debugpy() -> None:
    host = "127.0.0.1"
    port = 5678
    debugpy.listen((host, port))
    print(f"debugpy listening on {host}:{port}", flush=True)
    print(f"pid={Path('/proc/self').resolve().name}", flush=True)
    print("Waiting for client to attach before running…", flush=True)
    debugpy.wait_for_client()
    print("Client attached. Starting main().", flush=True)


if __name__ == "__main__":
    enable_debugpy()
    asyncio.run(main())
