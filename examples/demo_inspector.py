# /// script
# requires-python = ">=3.14"
# dependencies = [
#   "debugpy",
# ]
# ///

from __future__ import annotations

import time
from dataclasses import dataclass, field

import debugpy

GLOBAL_SENTINEL = "scope-global"


@dataclass(slots=True)
class InspectorBox:
    answer: int = 42
    label: str = "initial"
    tags: list[str] = field(default_factory=lambda: ["alpha", "beta", "gamma"])


def main() -> None:
    items = [f"item-{i:03d}" for i in range(120)]
    box = InspectorBox()
    debugpy.breakpoint()
    print(f"answer={box.answer} first={items[0]}", flush=True)
    time.sleep(120)


if __name__ == "__main__":
    main()
