from __future__ import annotations

from pathlib import Path

from yathaavat.app.picker_history import HistoryEntry, PickerHistory


def _make_history(tmp_path: Path, name: str = "test", max_entries: int = 50) -> PickerHistory:
    h = PickerHistory(name, max_entries=max_entries)
    h._path = tmp_path / f"{name}_history.json"
    return h


def test_push_and_load(tmp_path: Path) -> None:
    h = _make_history(tmp_path)
    h.push(HistoryEntry(command="foo.py", label="foo.py", timestamp=1000.0))
    entries = h.load()
    assert len(entries) == 1
    assert entries[0].command == "foo.py"
    assert entries[0].timestamp == 1000.0


def test_mru_ordering(tmp_path: Path) -> None:
    h = _make_history(tmp_path)
    h.push(HistoryEntry(command="old.py", label="old.py", timestamp=1000.0))
    h.push(HistoryEntry(command="new.py", label="new.py", timestamp=2000.0))
    entries = h.load()
    assert len(entries) == 2
    assert entries[0].command == "new.py"
    assert entries[1].command == "old.py"


def test_max_entries(tmp_path: Path) -> None:
    h = _make_history(tmp_path, max_entries=3)
    for i in range(5):
        h.push(HistoryEntry(command=f"cmd{i}.py", label=f"cmd{i}.py", timestamp=float(i)))
    entries = h.load()
    assert len(entries) == 3
    assert entries[0].command == "cmd4.py"


def test_dedup_updates_timestamp(tmp_path: Path) -> None:
    h = _make_history(tmp_path)
    h.push(HistoryEntry(command="foo.py", label="foo.py", timestamp=1000.0))
    h.push(HistoryEntry(command="foo.py", label="foo.py", timestamp=2000.0))
    entries = h.load()
    assert len(entries) == 1
    assert entries[0].timestamp == 2000.0


def test_corruption_recovery(tmp_path: Path) -> None:
    h = _make_history(tmp_path)
    h._path.write_text("not valid json {{{", encoding="utf-8")
    entries = h.load()
    assert entries == []


def test_remove(tmp_path: Path) -> None:
    h = _make_history(tmp_path)
    h.push(HistoryEntry(command="a.py", label="a.py", timestamp=1000.0))
    h.push(HistoryEntry(command="b.py", label="b.py", timestamp=2000.0))
    h.remove("a.py")
    entries = h.load()
    assert len(entries) == 1
    assert entries[0].command == "b.py"


def test_empty_load(tmp_path: Path) -> None:
    h = _make_history(tmp_path)
    entries = h.load()
    assert entries == []
