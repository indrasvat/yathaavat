from __future__ import annotations

import asyncio
import shlex
import time
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from textual import on
from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Container
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Input, ListItem, ListView, Static

from yathaavat.app.file_discovery import DiscoveredFile, discover_python_files
from yathaavat.app.fuzzy import fuzzy_match
from yathaavat.app.picker_history import HistoryEntry, PickerHistory
from yathaavat.core import SESSION_MANAGER, AppContext, SessionManager


@dataclass(frozen=True, slots=True)
class LaunchSpec:
    argv: list[str]


def parse_launch_spec(value: str) -> LaunchSpec | None:
    s = value.strip()
    if not s:
        return None
    try:
        argv = shlex.split(s)
    except ValueError:
        return None
    if not argv:
        return None
    return LaunchSpec(argv=argv)


def _relative_time(timestamp: float) -> str:
    delta = time.time() - timestamp
    if delta < 60:
        return "just now"
    if delta < 3600:
        return f"{int(delta / 60)}m ago"
    if delta < 86400:
        return f"{int(delta / 3600)}h ago"
    return f"{int(delta / 86400)}d ago"


class LaunchPicker(ModalScreen[None]):
    BINDINGS: ClassVar[list[BindingType]] = [("escape", "app.pop_screen", "Close")]

    query_text: reactive[str] = reactive("")

    def __init__(self, *, ctx: AppContext) -> None:
        super().__init__()
        self._ctx = ctx
        self._history = PickerHistory("launch")
        self._entries: list[HistoryEntry] = []
        self._files: list[DiscoveredFile] = []
        self._discover_task: asyncio.Task[None] | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self._loading = True

    def compose(self) -> ComposeResult:
        yield Container(
            Static("Launch under debugpy", id="launch_title"),
            Input(
                placeholder="Type to search files, or enter command…",
                id="launch_input",
            ),
            ListView(id="launch_list"),
            id="launch_root",
        )

    def on_mount(self) -> None:
        self.query_one("#launch_input", Input).focus()
        self._entries = self._history.load()
        self._discover_task = asyncio.create_task(self._discover_files())
        self._refresh_results()

    def on_unmount(self) -> None:
        if self._discover_task is not None:
            self._discover_task.cancel()

    async def _discover_files(self) -> None:
        try:
            files = await asyncio.to_thread(discover_python_files, Path.cwd())
            self._files = files
        except Exception:
            self._files = []
        self._loading = False
        self._refresh_results()

    @on(Input.Changed, "#launch_input")
    def _on_query(self, event: Input.Changed) -> None:
        self.query_text = event.value

    def watch_query_text(self) -> None:
        self._refresh_results()

    def _refresh_results(self) -> None:
        lv = self.query_one("#launch_list", ListView)
        lv.clear()

        q = self.query_text.strip()
        rows = self._build_rows(q)

        if not rows and self._loading:
            li = ListItem(Static("[dim]Scanning files…[/]", classes="launch_row"))
            lv.append(li)
            return

        if not rows and q:
            li = ListItem(
                Static(
                    "[dim]No matches. Press Enter to launch as command.[/]", classes="launch_row"
                )
            )
            lv.append(li)
            return

        for row in rows[:30]:
            li = ListItem(Static(row.label, classes="launch_row"))
            li.launch_command = row.command  # type: ignore[attr-defined]
            li.row_kind = row.kind  # type: ignore[attr-defined]
            lv.append(li)

    @dataclass(frozen=True, slots=True)
    class _Row:
        label: str
        command: str
        kind: str  # "history" | "file"
        score: int

    def _build_rows(self, query: str) -> list[_Row]:
        rows: list[LaunchPicker._Row] = []

        # History entries
        for entry in self._entries:
            if query:
                m = fuzzy_match(query, f"{entry.command} {entry.label}")
                if m is None:
                    continue
                score = m.score
            else:
                score = 0
            age = _relative_time(entry.timestamp)
            label = f"  [bold]{entry.command}[/]  [dim]{age}[/]"
            rows.append(self._Row(label=label, command=entry.command, kind="history", score=score))

        # Discovered files
        for f in self._files:
            if query:
                m = fuzzy_match(query, f.path)
                if m is None:
                    continue
                score = m.score
            else:
                score = 100 if not f.boost else 50
            prefix = "★" if f.boost else " "
            label = f"  {prefix} {f.path}"
            rows.append(self._Row(label=label, command=f.path, kind="file", score=score))

        if query:
            rows.sort(key=lambda r: (r.score, r.command))
        else:
            # No query: history first (MRU), then files (boosted first)
            history_rows = [r for r in rows if r.kind == "history"]
            file_rows = [r for r in rows if r.kind == "file"]
            rows = history_rows + file_rows

        return rows

    @on(Input.Submitted, "#launch_input")
    def _on_submit(self, event: Input.Submitted) -> None:
        # Try to use the selected list item first
        lv = self.query_one("#launch_list", ListView)
        if lv.index is not None and lv.index >= 0:
            items = list(lv.children)
            if lv.index < len(items):
                item = items[lv.index]
                cmd = getattr(item, "launch_command", None)
                if isinstance(cmd, str) and cmd:
                    self._do_launch(cmd)
                    return

        # Fall back to raw input
        self._do_launch(event.value)

    @on(ListView.Selected, "#launch_list")
    def _on_selected(self, event: ListView.Selected) -> None:
        cmd = getattr(event.item, "launch_command", None)
        if isinstance(cmd, str) and cmd:
            self._do_launch(cmd)

    def _do_launch(self, raw: str) -> None:
        # Expand tilde in the command
        expanded = _expand_tilde(raw)
        spec = parse_launch_spec(expanded)
        if spec is None:
            self._ctx.host.notify("Invalid command.", timeout=2.0)
            return

        manager: SessionManager | None
        try:
            manager = self._ctx.services.get(SESSION_MANAGER)
        except KeyError:
            manager = None

        if manager is None:
            self._ctx.host.notify("No session backend available.", timeout=2.0)
            self.app.pop_screen()
            return

        # Save to history
        self._history.push(
            HistoryEntry(command=raw.strip(), label=raw.strip(), timestamp=PickerHistory.now())
        )

        self._ctx.host.notify("Launching…", timeout=2.0)

        async def _launch() -> None:
            try:
                await manager.launch(spec.argv)
            except Exception as exc:
                self._ctx.host.notify(str(exc), timeout=3.0)

        task = asyncio.create_task(_launch())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        self.app.pop_screen()


def _expand_tilde(value: str) -> str:
    """Expand ~ in the first token of a launch command."""
    s = value.strip()
    if not s:
        return s
    try:
        parts = shlex.split(s)
    except ValueError:
        return s
    if not parts:
        return s
    first = parts[0]
    if "~" in first:
        expanded = str(Path(first).expanduser())
        parts[0] = expanded
        return shlex.join(parts)
    return s
