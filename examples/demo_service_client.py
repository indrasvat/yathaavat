# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///

from __future__ import annotations

import argparse
import random
import time
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass(frozen=True, slots=True)
class Args:
    base: str
    duration_s: float
    interval_s: float
    break_after_s: float | None


def _parse_args() -> Args:
    p = argparse.ArgumentParser(prog="demo_service_client", add_help=True)
    p.add_argument("--base", default="http://127.0.0.1:8000", help="Base URL for the service.")
    p.add_argument("--duration", type=float, default=30.0, help="Run duration in seconds.")
    p.add_argument("--interval", type=float, default=0.75, help="Seconds between requests.")
    p.add_argument(
        "--break-after",
        type=float,
        default=None,
        help="Call /debug/break after N seconds (requires yathaavat connected).",
    )
    ns = p.parse_args()
    return Args(
        base=ns.base.rstrip("/"),
        duration_s=float(ns.duration),
        interval_s=float(ns.interval),
        break_after_s=float(ns.break_after) if ns.break_after is not None else None,
    )


def _get(url: str) -> str:
    req = Request(url, method="GET")
    with urlopen(req, timeout=8) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _post_form(url: str, data: dict[str, str]) -> str:
    body = urlencode(data).encode("utf-8")
    req = Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urlopen(req, timeout=8) as resp:
        return resp.read().decode("utf-8", errors="replace")


def main() -> int:
    args = _parse_args()
    start = time.monotonic()
    did_break = False
    rng = random.Random(0xC0FFEE)

    print(f"Driving {args.base} for {args.duration_s:.1f}s (interval {args.interval_s:.2f}s)")
    print("Tip: start yathaavat and connect to the service's debugpy port, then use --break-after.")

    while True:
        elapsed = time.monotonic() - start
        if elapsed >= args.duration_s:
            break

        try:
            roll = rng.random()
            if args.break_after_s is not None and not did_break and elapsed >= args.break_after_s:
                print("→ /debug/break")
                _get(f"{args.base}/debug/break")
                did_break = True
            elif roll < 0.55:
                _get(f"{args.base}/health")
            elif roll < 0.75:
                _get(f"{args.base}/orders/checkout?id=8812&subtotal=129.95&tax=10.40")
            elif roll < 0.9:
                limit = int(120_000 + rng.random() * 200_000)
                _get(f"{args.base}/cpu/primes?limit={limit}")
            else:
                _post_form(f"{args.base}/jobs/submit", {"kind": "primes", "limit": "250000"})
        except HTTPError as exc:
            print(f"HTTP {exc.code}: {exc.reason}")
        except URLError as exc:
            print(f"network error: {exc}")

        time.sleep(args.interval_s)

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
