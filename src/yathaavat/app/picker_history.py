from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import platformdirs


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    command: str
    label: str
    timestamp: float


class PickerHistory:
    def __init__(self, name: str, *, max_entries: int = 50) -> None:
        self._name = name
        self._max_entries = max_entries
        cache_dir = Path(platformdirs.user_cache_dir("yathaavat"))
        cache_dir.mkdir(parents=True, exist_ok=True)
        self._path = cache_dir / f"{name}_history.json"

    def load(self) -> list[HistoryEntry]:
        try:
            raw = self._path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, json.JSONDecodeError, ValueError):
            return []
        if not isinstance(data, list):
            return []
        entries: list[HistoryEntry] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            command = item.get("command")
            label = item.get("label")
            timestamp = item.get("timestamp")
            if (
                isinstance(command, str)
                and isinstance(label, str)
                and isinstance(timestamp, int | float)
            ):
                entries.append(
                    HistoryEntry(command=command, label=label, timestamp=float(timestamp))
                )
        entries.sort(key=lambda e: e.timestamp, reverse=True)
        return entries[: self._max_entries]

    def push(self, entry: HistoryEntry) -> None:
        entries = self.load()
        entries = [e for e in entries if e.command != entry.command]
        entries.insert(0, entry)
        entries = entries[: self._max_entries]
        self._write(entries)

    def remove(self, command: str) -> None:
        entries = self.load()
        entries = [e for e in entries if e.command != command]
        self._write(entries)

    def _write(self, entries: list[HistoryEntry]) -> None:
        data = [{"command": e.command, "label": e.label, "timestamp": e.timestamp} for e in entries]
        payload = json.dumps(data, indent=2)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
        closed = False
        try:
            os.write(fd, payload.encode("utf-8"))
            os.close(fd)
            closed = True
            os.replace(tmp, self._path)
        except BaseException:
            if not closed:
                os.close(fd)
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    @staticmethod
    def now() -> float:
        return time.time()
