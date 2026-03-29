from __future__ import annotations


def find_next_index(text: str, query: str, start_index: int) -> int | None:
    """Return the next match index (wrapping) after start_index."""

    if not query or not text:
        return None

    start = max(min(start_index + 1, len(text)), 0)
    found = text.find(query, start)
    if found < 0:
        found = text.find(query, 0)
    return None if found < 0 else found


def find_prev_index(text: str, query: str, start_index: int) -> int | None:
    """Return the previous match index (wrapping) before start_index."""

    if not query or not text:
        return None

    end = max(min(start_index, len(text)), 0)
    found = text.rfind(query, 0, end)
    if found < 0:
        found = text.rfind(query)
    return None if found < 0 else found
