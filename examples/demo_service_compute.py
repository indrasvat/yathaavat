# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True, slots=True)
class PrimeStats:
    limit: int
    count: int
    last_prime: int | None


@lru_cache(maxsize=64)
def prime_stats(limit: int) -> PrimeStats:
    """Compute primes up to `limit` (inclusive) using a simple sieve."""
    if limit < 2:
        return PrimeStats(limit=limit, count=0, last_prime=None)

    sieve = bytearray(b"\x01") * (limit + 1)
    sieve[0:2] = b"\x00\x00"

    p = 2
    while p * p <= limit:
        if sieve[p]:
            start = p * p
            sieve[start : limit + 1 : p] = b"\x00" * (((limit - start) // p) + 1)
        p += 1

    last_prime: int | None = None
    count = 0
    for i, is_prime in enumerate(sieve):
        if is_prime:
            count += 1
            last_prime = i

    return PrimeStats(limit=limit, count=count, last_prime=last_prime)


def mandelbrot_ascii(*, width: int, height: int, max_iter: int) -> str:
    """Render a small ASCII Mandelbrot set (CPU-heavy, Python-level loops)."""
    if width <= 0 or height <= 0:
        return ""
    if max_iter <= 0:
        max_iter = 1

    shades = " .:-=+*#%@"
    rows: list[str] = []
    h_denom = max(height - 1, 1)
    w_denom = max(width - 1, 1)

    for y in range(height):
        cy = (y / h_denom) * 2.0 - 1.0
        row_chars: list[str] = []
        for x in range(width):
            cx = (x / w_denom) * 3.0 - 2.0
            c = complex(cx, cy)
            z = 0j
            it = 0
            while (z.real * z.real + z.imag * z.imag) <= 4.0 and it < max_iter:
                z = z * z + c
                it += 1
            shade_index = (it * (len(shades) - 1)) // max_iter
            row_chars.append(shades[shade_index])
        rows.append("".join(row_chars))

    return "\n".join(rows)
