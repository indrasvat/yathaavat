from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class InputHistory:
    """A small readline-style history buffer.

    Designed for TUI inputs where ↑ / ↓ should cycle prior submissions while
    preserving whatever the user was typing before entering history mode.
    """

    max_entries: int = 200
    _items: list[str] = field(default_factory=list, init=False)
    _cursor: int | None = field(default=None, init=False)
    _scratch: str = field(default="", init=False)

    def push(self, value: str) -> None:
        v = value.strip()
        if not v:
            return
        if self._items and self._items[-1] == v:
            self.reset_navigation()
            return
        self._items.append(v)
        if len(self._items) > self.max_entries:
            overflow = len(self._items) - self.max_entries
            del self._items[:overflow]
        self.reset_navigation()

    def prev(self, current_value: str) -> str | None:
        if not self._items:
            return None
        if self._cursor is None:
            self._scratch = current_value
            self._cursor = len(self._items) - 1
            return self._items[self._cursor]
        if self._cursor <= 0:
            return self._items[0]
        self._cursor -= 1
        return self._items[self._cursor]

    def next(self) -> str | None:
        if self._cursor is None:
            return None
        if self._cursor < len(self._items) - 1:
            self._cursor += 1
            return self._items[self._cursor]
        self._cursor = None
        return self._scratch

    def reset_navigation(self) -> None:
        self._cursor = None
        self._scratch = ""

    def items(self) -> tuple[str, ...]:
        return tuple(self._items)
