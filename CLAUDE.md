# yathaavat — Agent Instructions

Terminal-first visual debugger for Python 3.14+ (Textual UI + debugpy/DAP).

## Project overview

yathaavat speaks DAP to debugpy and renders a tri-pane TUI (Stack/Source/Locals) with breakpoints, watches, console, transcript, and threads. It supports launch (`Ctrl+R`), connect (`Ctrl+K`), and attach (`Ctrl+A`) workflows. Designed for SSH/tmux, keyboard-first, mouse-optional.

**Design doc:** `docs/DESIGN_v2.md` (the authoritative spec).

## Architecture

```text
src/yathaavat/
  core/           # Domain: session store, DAP client, commands, services, plugins
  app/            # Textual UI: panels, dialogs, layout, chrome, expression editor
  plugins/        # Entry-point plugins: builtin (commands/widgets), debugpy, processes
  cli.py          # Entry point: `yathaavat tui`
```

Key patterns:
- **DI via AppContext**: registries (CommandRegistry, WidgetRegistry, ServiceRegistry) passed to plugins
- **Observable SessionStore**: frozen `SessionSnapshot` dataclass, listeners notified on every update
- **Protocol-based extension**: `SessionManager`, `SafeAttachManager`, `VariablesManager`, etc. are `runtime_checkable` Protocols
- **ServiceKey[T]**: strongly-typed DI keys (`SESSION_STORE`, `SESSION_MANAGER`)
- **Plugin system**: `pyproject.toml` entry points under `yathaavat.plugins`
- **Frozen dataclasses with slots**: all data types use `@dataclass(frozen=True, slots=True)`

## Development

```bash
make sync          # Install deps (requires uv + python3.14)
make run           # Launch TUI
make test          # pytest (71 tests, <1s)
make lint          # ruff check
make format        # ruff format
make typecheck     # mypy --strict
make check         # format-check + lint + typecheck + test (pre-push hook)
make version       # Show current version (from git tags)
make build-dist    # Build wheel + sdist
make release V=x.y.z  # Tag, push, build, create GitHub release
```

Demo flows:
```bash
make demo-service          # HTTP service with debugpy (connect via Ctrl+K)
make vanilla-service       # Plain HTTP service (attach via Ctrl+A)
make shux-smoke            # Automated shux TUI smoke screenshot
```

## CI/CD

**CI** (`.github/workflows/ci.yml`): Runs on push to main and PRs — format check, ruff lint, mypy strict, pytest, shellcheck on install.sh.

**Release** (`.github/workflows/release.yml`): Triggered by `v*` tag push — runs full checks, builds wheel + sdist via `uv build`, creates GitHub Release with artifacts and auto-generated notes.

## Versioning and releases

Version is derived from **git tags** via `hatch-vcs` — never hardcode a version string.

```bash
# Create a release (runs local checks, tags, pushes — GH Actions builds + publishes)
make release V=0.2.0

# Users install via uvx (no PyPI needed)
uvx --from git+https://github.com/indrasvat/yathaavat yathaavat
uvx --from git+https://github.com/indrasvat/yathaavat@v0.2.0 yathaavat
```

Between tags, `__version__` shows dev versions like `0.1.dev38` (38 commits since last tag).

## Code conventions

- **Python 3.14+** — use modern syntax: `type` aliases, `StrEnum`, `match/case`, `X | Y` unions
- **`from __future__ import annotations`** in every file
- **Ruff** lint rules: E, F, I, N, UP, B, RUF. Line length: 100
- **mypy strict** — full type annotations required on all public APIs
- **Imports**: prefer importing from `yathaavat.core` (the public barrel), not sub-modules
- **No docstrings on obvious methods** — code should be self-evident; docstrings only where logic isn't obvious
- **Async all the way**: DAP operations are async; never block the Textual event loop
- **Textual CSS** for layout, not inline styles
- **Never manually edit `pyproject.toml` dependency versions or `uv.lock`** — use `uv` commands:
  - `uv add <pkg>` — add a new dependency
  - `uv add --dev <pkg>` — add a dev dependency
  - `uv sync --upgrade-package <pkg>` — upgrade a specific package
  - `uv sync --upgrade` — upgrade all packages
  - `uv lock --upgrade` — regenerate lockfile with latest versions
  - Manual version edits bypass uv's resolver and can produce inconsistent lockfiles

## Test patterns

Tests live in `tests/`. Follow existing conventions:

- **File naming**: `test_{module_name}.py` — one test file per source module
- **Function naming**: `test_{what}_{scenario}` — e.g., `test_parse_breakpoint_spec_with_condition`
- **Use `tmp_path`** for filesystem fixtures (pytest built-in)
- **No test classes** — standalone test functions only
- **Mocking**: create `_Test*` stub classes (see `test_run_to_cursor.py`, `test_dap_client.py`)
- **Assert exact values** — no fuzzy assertions; check specific fields
- **Test edge cases**: invalid input, empty state, boundary conditions
- **No end-to-end TUI tests** in pytest — use shux automation for visual verification

## Key bindings (reference)

| Key | Action | Context |
|-----|--------|---------|
| `Ctrl+R` | Launch | Global |
| `Ctrl+K` | Connect | Global |
| `Ctrl+A` | Attach | Global |
| `Ctrl+P` | Command palette | Global |
| `Ctrl+Q` | Quit | Global |
| `Ctrl+X` | Disconnect/Terminate | Global |
| `c` | Continue | Paused |
| `n` | Step over | Paused |
| `s` | Step in | Paused |
| `u` | Step out | Paused |
| `p` | Pause | Running |
| `b` | Toggle breakpoint | Source focused |
| `Ctrl+B` | Add breakpoint dialog | Global |
| `Ctrl+W` | Add watch | Global |
| `Ctrl+F` / `/` | Find in source | Source focused |
| `Ctrl+G` | Go to line | Source focused |
| `Ctrl+E` | Jump to execution line | Source focused |
| `Enter` | Run to cursor | Source focused, paused |
| `F6` | Cycle focus | Global |
| `Esc` | Cancel/close | Global |

## shux visual testing

For terminal UI automation, load the `shux` SKILL and use shux for driving panes,
waiting on screen text, and capturing screenshots. If shux or the skill is not
installed, install both with:

```bash
curl -sSf https://shux.pages.dev/install.sh | sh
```

Committed shux specs live in `.shux/templates/`. Screenshots, logs, and other
ephemeral artifacts go to `.shux/out/` (gitignored).

When running TUIs or taking shux screenshots, always clear `NO_COLOR` and set
`TERM=xterm-256color COLORTERM=truecolor FORCE_COLOR=1` so color rendering is
exercised.

Run: `make shux-smoke`

---

## New feature protocol

Follow this workflow for every new feature, bug fix, or enhancement:

### 1. Branch

```bash
git fetch origin main
git checkout -b <type>/<short-name> origin/main
# Types: feat/, fix/, refactor/, test/, docs/
# Examples: feat/exception-panel, fix/variable-paging, refactor/dap-timeout
```

### 2. Plan

- Read `docs/DESIGN_v2.md` for context — check if the feature is specified there
- Identify which layer the change touches: `core/`, `app/`, `plugins/`
- List affected files and the expected public API changes
- If the change touches `SessionSnapshot` or `SessionManager`, consider downstream effects on all panels

### 3. Implement

- Make the smallest change that delivers the feature
- Core logic in `core/` or `plugins/`, UI in `app/`
- New commands: register in the appropriate plugin's `register()` method
- New panels: add `WidgetContribution` in the plugin, wire in `tui.py` layout
- New protocols: add to `core/session.py`, export from `core/__init__.py`
- Follow existing patterns — read neighboring code before writing

### 4. Test

Write tests in `tests/test_{module}.py` following existing patterns:

```python
from __future__ import annotations
# Import from the module under test
from yathaavat.app.breakpoint import parse_breakpoint_spec

def test_feature_happy_path(tmp_path: Path) -> None:
    # Arrange — set up fixtures
    # Act — call the function
    # Assert — check specific values
    ...

def test_feature_edge_case() -> None:
    ...
```

Run and verify:
```bash
make test       # All tests must pass
make check      # Full lint + type + test suite
```

### 5. Visual verification

Load the `shux` SKILL and create or update shux automation to exercise the new
feature visually. If shux or the skill is not installed, install both with
`curl -sSf https://shux.pages.dev/install.sh | sh`. The automation must:

- Drive the specific new UI through keyboard interaction
- Capture screenshots at each verification point
- Verify screen text contains expected output
- Verify TUI colors, alignment, keyboard navigation, and panel layout
- Clean up all shux sessions/panes with traps or `finally` blocks

Screenshots and logs go to `.shux/out/` (gitignored — never commit them).
Reusable shux templates or scripts under `.shux/templates/` or `.shux/scripts/`
are committed.

Run: `make shux-smoke` (or the specific shux automation target)

### 6. Lint and format

```bash
make format     # Auto-format
make lint       # Lint check
make typecheck  # mypy strict
make check      # All-in-one gate
```

Fix all issues before proceeding.

### 7. Update docs

- If the feature is in `docs/DESIGN_v2.md`, update the implementation status
- If the feature adds new key bindings, update the `README.md` key reference
- If the feature adds new demo flows, add a `make` target and document it

### 8. Commit and push

```bash
git add <specific files>
git commit -m "<type>(<scope>): <description>"
# Examples:
#   feat(panels): add exception details panel
#   fix(dap): handle variable paging overflow
#   test(breakpoint): add condition parsing edge cases
git push -u origin <branch-name>
```

### 9. Create PR

```bash
gh pr create --title "<type>(<scope>): <description>" --body "..."
```

PR body format:
```markdown
## Summary
- <1-3 bullet points describing what and why>

## Test plan
- [ ] `make check` passes
- [ ] shux visual verification screenshots reviewed
- [ ] <feature-specific verification steps>
```

### 10. Address review

Load the `gh-ghent` skill and follow PR monitoring/review comment flow:
- Check CI status and review comments
- Address feedback with fixup commits
- Re-run `make check` after each round of changes
- Request re-review once all comments are addressed

### 11. Merge, release, and verify

```bash
# Squash-merge the PR and delete the remote branch
gh pr merge <PR-number> --squash --delete-branch

# Switch to main and pull the merge commit
git checkout main
git pull origin main

# Wait for CI to pass on main
gh run watch

# Tag a new minor version (bump from current)
make release V=x.y.z    # runs local checks, tags, pushes

# Wait for the release CI workflow to complete
gh run watch

# Install the released version and verify
curl -fsSL https://raw.githubusercontent.com/indrasvat/yathaavat/main/install.sh | bash
yathaavat --version
```

## Implementation status (vs DESIGN_v2.md)

Implemented: session state machine, DAP client, launch/connect/attach, breakpoints (toggle/conditions/logpoints/queued), stepping, source view (gutter markers, find, go-to-line, run-to-cursor), stack, locals (expansion), watches, console (expression editor + completions), transcript, threads, command palette, status/help chrome, layout breakpoints, exception panel (traceback tree, chained exceptions, ExceptionGroup, exception breakpoints), smart pickers (fuzzy file discovery for launch, server discovery for connect, persistent MRU history, tilde expansion).

Not yet started: safe attach via `sys.remote_exec` (M3), async tasks panel, process tree, settings panel, theming/ASCII mode, transcript JSONL export, doctor bundle, plugin renderers.
