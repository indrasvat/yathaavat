# yathaavat

> *yathāvat* (Sanskrit): “as it is”, “accurately / truly” — a debugger focused on faithful, low-friction visibility.

Terminal-first visual debugger for **Python 3.14+** (Textual UI + debugpy/DAP), designed for fast, keyboard-driven workflows.

## What you get

- **Launch / Connect / Attach**: `Ctrl+R` launch a target, `Ctrl+K` connect to `host:port`, `Ctrl+A` attach to a local process.
- **Breakpoints**: toggle at cursor (`b`), add by `file:line` (`Ctrl+B`), queued while disconnected and applied on connect.
- **Fast navigation**: inline Find (`Ctrl+F` or `/`), Go to line (`Ctrl+G`), Jump to execution (`Ctrl+E`), Run to cursor (`Enter`).
- **Debugger essentials**: continue (`c`), pause (`p`), step over (`n`), step in (`s`), step out (`u`).
- **Inspection**: stack, locals (expand/copy), watches, transcript, command palette (`Ctrl+P`).

## Install

Prereqs: `uv` + `python3.14`.

```bash
# One-liner
curl -fsSL https://raw.githubusercontent.com/indrasvat/yathaavat/main/install.sh | bash

# Or run directly without installing
uvx --from git+https://github.com/indrasvat/yathaavat yathaavat

# Or install manually
uv tool install --python python3.14 git+https://github.com/indrasvat/yathaavat

# Pin a release
uvx --from git+https://github.com/indrasvat/yathaavat@v0.1.0 yathaavat
```

## Quickstart (dev)

```bash
make sync
make run
```

Inside the TUI:
- `Ctrl+R` → `examples/demo_target.py`
- `Ctrl+P` command palette (discover everything)
- `Ctrl+Q` quit

## Demo flows

### Launch (single-file)

1) `make run`
2) `Ctrl+R` → `examples/demo_target.py`

### Connect (debugpy server)

```bash
YATHAAVAT_DEMO_PORT=5678 uv run --python python3.14 examples/demo_app.py
```

Then in the TUI: `Ctrl+K` → `127.0.0.1:5678`.

### Long-lived HTTP service (realistic)

1) Terminal A: `make demo-service`
2) Terminal B: `make run` → `Ctrl+K` → `127.0.0.1:5678`
3) Drive endpoints:

```bash
curl -fsS http://127.0.0.1:8000/health
curl -fsS 'http://127.0.0.1:8000/cpu/primes?limit=200000'
curl -fsS 'http://127.0.0.1:8000/debug/break'   # pauses only while yathaavat is connected
```

Optional load generator:

```bash
uv run --python python3.14 examples/demo_service_client.py --break-after 5
```

### Vanilla HTTP service (no debugpy in code)

This service has **zero debugpy imports**; it’s a plain stdlib HTTP server with CPU + job endpoints.

1) Terminal A: `make vanilla-service`
2) Terminal B:
   - macOS: `sudo make run` → `Ctrl+A` → select `examples/vanilla_service.py` → Enter
   - Linux: `make run` → `Ctrl+A` (may still require ptrace perms depending on distro policy)
3) Hit endpoints to exercise breakpoints / stepping:

```bash
curl -fsS http://127.0.0.1:8001/health
curl -fsS 'http://127.0.0.1:8001/compute/primes?limit=200000'
curl -fsS 'http://127.0.0.1:8001/jobs/enqueue?kind=primes&limit=250000'
```

## Notes (macOS)

- Attaching to an existing PID can require elevated privileges / entitlements; when blocked, yathaavat times out and shows actionable transcript output.
- For the smoothest experience, prefer `Launch` (`Ctrl+R`) or connecting to an already-listening debugpy server (`Ctrl+K`).

## Docs

- `docs/DESIGN_v2.md` — current design + interaction model
- `docs/mocks.html` — UI direction (HTML mocks)
- `docs/research/README.md` — research index (landscape, terminal constraints, UX best practices)

## Development

- `make help` — list targets
- `make check` — format/lint/typecheck/tests
- `make hooks` — install `pre-push` hook (runs `make check`)
- `make iterm2` / `make iterm2-demo-service` / `make iterm2-safe` — scripted iTerm2 runs + screenshots (always cleaned up)
