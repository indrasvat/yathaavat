# /// script
# requires-python = ">=3.14"
# dependencies = [
#   "debugpy",
# ]
# ///

from __future__ import annotations

import time
from dataclasses import dataclass

import debugpy


@dataclass(slots=True)
class Order:
    id: int
    subtotal: float
    tax: float
    discount: float = 0.0


def compute_total(order: Order) -> float:
    return order.subtotal + order.tax - order.discount


def checkout(order: Order) -> float:
    total = compute_total(order)
    debugpy.breakpoint()
    return total


def main() -> None:
    order = Order(id=8812, subtotal=129.95, tax=10.40)
    total = checkout(order)
    print(f"TOTAL {total}", flush=True)
    time.sleep(120)


if __name__ == "__main__":
    main()
