from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FuzzyMatch:
    """Result of fuzzy matching against a candidate string.

    Lower scores are better.
    """

    score: int


def fuzzy_match(query: str, candidate: str) -> FuzzyMatch | None:
    """Return a fuzzy match score for query against candidate.

    The algorithm is intentionally simple and deterministic:
    - query matches if all non-space characters appear in order in candidate
    - score prefers earlier matches and contiguous runs
    """

    q = "".join(ch for ch in query.strip().lower() if not ch.isspace())
    if not q:
        return FuzzyMatch(score=0)

    c = candidate.lower()
    pos = -1
    first: int | None = None
    gaps = 0

    for ch in q:
        idx = c.find(ch, pos + 1)
        if idx < 0:
            return None
        if first is None:
            first = idx
        else:
            gap = idx - pos - 1
            if gap > 0:
                gaps += gap
        pos = idx

    assert first is not None
    # Weight early matches heavily; then prefer fewer gaps.
    return FuzzyMatch(score=first * 10 + gaps)
