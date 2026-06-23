from __future__ import annotations

import asyncio
import shlex
import sys
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
    debugpy_prefix: list[str] | None = None
    cwd: str | None = None


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
    return _normalise_launch_argv(argv)


def _normalise_launch_argv(argv: list[str]) -> LaunchSpec | None:
    if Path(argv[0]).name != "uv":
        return LaunchSpec(argv=argv)

    return _normalise_uv_run(argv)


def _normalise_uv_run(argv: list[str]) -> LaunchSpec | None:
    """Translate common uv console-script launches into debugpy launches.

    debugpy runs Python files/modules; it does not resolve arbitrary commands from PATH.
    For `uv --directory app run tool ...`, run debugpy inside uv's target environment and
    point it at the generated console-script wrapper.
    """

    invocation_cwd = Path.cwd()
    run_cwd = invocation_cwd
    project_dir = invocation_cwd
    prefix_args = [argv[0]]
    run_index: int | None = None

    i = 1
    while i < len(argv):
        token = argv[i]
        if token == "run":
            run_index = i
            prefix_args.append(token)
            break
        if token in {"--directory", "--project"}:
            i += 1
            if i >= len(argv):
                return None
            value = _resolve_project_dir(argv[i], base=invocation_cwd)
            if token == "--directory":
                run_cwd = value
                project_dir = value
            else:
                project_dir = value
            prefix_args.extend([token, str(value)])
        elif token.startswith("--directory="):
            run_cwd = _resolve_project_dir(token.removeprefix("--directory="), base=invocation_cwd)
            project_dir = run_cwd
            prefix_args.append(f"--directory={run_cwd}")
        elif token.startswith("--project="):
            project_dir = _resolve_project_dir(
                token.removeprefix("--project="), base=invocation_cwd
            )
            prefix_args.append(f"--project={project_dir}")
        else:
            prefix_args.append(token)
        i += 1

    if run_index is None:
        return None

    run_options, target = _split_uv_run_options(argv[run_index + 1 :])
    if not target:
        return None

    first = target[0]
    if first in {"python", "python3", "python3.14"}:
        if len(target) < 2:
            return None
        return LaunchSpec(
            argv=target[1:],
            debugpy_prefix=[*prefix_args, *run_options, "--with", "debugpy", "python"],
            cwd=str(run_cwd),
        )

    target_path = Path(first).expanduser()
    if target_path.is_absolute() or "/" in first:
        if not target_path.is_absolute():
            target_path = run_cwd / target_path
        return LaunchSpec(
            argv=[str(target_path.resolve()), *target[1:]],
            debugpy_prefix=[*prefix_args, *run_options, "--with", "debugpy", "python"],
            cwd=str(run_cwd),
        )

    script_path = project_dir / ".venv" / ("Scripts" if sys.platform == "win32" else "bin") / first
    if not script_path.exists():
        return None

    return LaunchSpec(
        argv=[str(script_path.resolve()), *target[1:]],
        debugpy_prefix=[*prefix_args, *run_options, "--with", "debugpy", "python"],
        cwd=str(run_cwd),
    )


_UV_RUN_OPTIONS_WITH_VALUE = {
    "-p",
    "--python",
    "--with",
    "--with-editable",
    "--with-requirements",
    "--env-file",
    "--index",
    "--default-index",
    "--index-url",
    "--extra-index-url",
    "--find-links",
    "--config-file",
}


def _split_uv_run_options(args: list[str]) -> tuple[list[str], list[str]]:
    options: list[str] = []
    i = 0
    while i < len(args):
        token = args[i]
        if token == "--":
            return options, args[i + 1 :]
        if not token.startswith("-"):
            return options, args[i:]

        options.append(token)
        if _uv_run_option_takes_value(token):
            i += 1
            if i >= len(args):
                return options, []
            options.append(args[i])
        i += 1

    return options, []


def _uv_run_option_takes_value(token: str) -> bool:
    if "=" in token:
        return False
    return token in _UV_RUN_OPTIONS_WITH_VALUE


def _resolve_project_dir(value: str, *, base: Path | None = None) -> Path:
    p = Path(value).expanduser()
    if not p.is_absolute():
        p = (base or Path.cwd()) / p
    return p.resolve()


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
        if rows and lv.index is None:
            lv.index = 0

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
            file_rows = sorted(
                (r for r in rows if r.kind == "file"),
                key=lambda r: (r.score, r.command),
            )
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
                kind = getattr(item, "row_kind", "")
                if isinstance(cmd, str) and cmd:
                    self._do_launch(cmd, kind=kind if isinstance(kind, str) else "")
                    return

        # Fall back to raw input
        self._do_launch(event.value)

    @on(ListView.Selected, "#launch_list")
    def _on_selected(self, event: ListView.Selected) -> None:
        cmd = getattr(event.item, "launch_command", None)
        kind = getattr(event.item, "row_kind", "")
        if isinstance(cmd, str) and cmd:
            self._do_launch(cmd, kind=kind if isinstance(kind, str) else "")

    def _do_launch(self, raw: str, *, kind: str = "") -> None:
        # For discovered files, quote the path to handle spaces
        if kind == "file":
            raw = shlex.quote(raw)
        # Expand tilde in the command
        expanded = _expand_tilde(raw)
        spec = parse_launch_spec(expanded)
        if spec is None:
            self._ctx.host.notify(
                "Invalid launch. Use a Python file/module or a synced uv run command.",
                timeout=3.0,
            )
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

        # Save to history with the expanded (absolute) command for cross-cwd portability
        self._history.push(
            HistoryEntry(command=expanded.strip(), label=raw.strip(), timestamp=PickerHistory.now())
        )

        self._ctx.host.notify("Launching…", timeout=2.0)

        async def _launch() -> None:
            try:
                await manager.launch(
                    spec.argv,
                    debugpy_prefix=spec.debugpy_prefix,
                    cwd=spec.cwd,
                )
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
