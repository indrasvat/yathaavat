# yathaavat

Terminal-first visual debugger for **Python 3.14+** (Textual UI + debugpy/DAP).

## Quickstart

```bash
make sync
make run
```

Inside the TUI:
- `Ctrl+R` launch a target (try `examples/demo_target.py`)
- `Ctrl+K` connect to a debugpy server (`host:port`)
- `Ctrl+A` attach to a local process (connects to `dap host:port` when detected; shows `safe` for Python 3.14+)
- `b/F9` toggle breakpoint, `n/F10` step, `c/F5` continue
- `Ctrl+P` command palette, `Ctrl+Q` quit

## Demo flows

**Launch**
1) `make run`
2) `Ctrl+R` → `examples/demo_target.py`

**Connect**
```bash
YATHAAVAT_DEMO_PORT=5678 uv run --python python3.14 examples/demo_app.py
```
Then in the TUI: `Ctrl+K` → `127.0.0.1:5678`

## Notes (macOS)

- Attaching to an existing PID (either via `sys.remote_exec` or `debugpy --pid`) may require elevated privileges and/or developer entitlements; when blocked, yathaavat times out and shows actionable transcript output.
- For the smoothest experience, prefer `Launch` (`Ctrl+R`) or connecting to an already-listening debugpy server (`Ctrl+K`).

## Dev

- `make check` (format/lint/typecheck/tests)
- `make hooks` (installs pre-push hook)
- `make iterm2` (drives the TUI in iTerm2 and captures screenshots)
- `make iterm2-safe` (drives the attach flow; on macOS, PID attach may be blocked by OS policy)
