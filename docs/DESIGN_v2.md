# yathaavat — Design v2 (Python 3.14+ TUI Visual Debugger)

**Doc version:** v2.0 (2025-12-20)  
**Target:** Python **3.14+** (CPython) • macOS/Linux first, Windows where feasible  
**North star:** A *daily-driver* terminal debugger: instant, keyboard-first, safe attach, and incident-friendly.

This redesign incorporates findings from `docs/research/` and closes the biggest gaps in `docs/DESIGN.md`:
- explicit interaction model (state machine + focus model),
- terminal-first layouts (80×24 → 160×45),
- production-grade safe attach design (`sys.remote_exec`),
- DAP realities (variable paging, breakpoint verification, object lifetimes),
- performance budgets and virtualization rules.

---

## 1) Product definition

**yathaavat** is a **Textual** TUI debugger with a **scriptable CLI** and a **transcript-first** workflow. It speaks **DAP** to a debug backend (default: `debugpy`) and, on Python 3.14+, supports **safe attach by PID** via `sys.remote_exec()` (PEP 768).

The goal is not “a terminal IDE”. It’s a debugger you happily use *every day* over SSH, in tmux splits, and under production constraints.

---

## 2) Success criteria (v2)

### Developer delight
- One command to start any golden workflow.
- UI is obvious at first glance: “where am I, why stopped, what changed?”
- No dead ends: every error offers a next action.

### Performance-first
- Keystroke → visual response feels instant.
- No unbounded operations on UI thread (all big work paged/virtualized).

### Ergonomics
- Keyboard-driven by default, mouse as optional convenience.
- Minimal but strong focus cues, consistent `Enter` and `Esc`.
- Discoverability via command palette + contextual help.

### Production-ready realism
- Safe attach is secure-by-default and explains permission requirements.
- Handles terminal quirks: key ambiguity, unicode width, no truecolor.
- Supports “support bundle” export with sensible redaction.

---

## 3) Key technical decisions

### 3.1 UI framework: Textual + Rich
Rationale:
- mature layout primitives, widgets, and event loop integration,
- built-in testing ecosystem and terminal capability detection,
- aligns with modern terminal protocols (including kitty keyboard protocol support via Textual).

### 3.2 Protocol surface: DAP as the primary “backend contract”
Rationale:
- decouples UI innovation from backend specifics,
- supports `debugpy` today, and leaves room for future backends.

### 3.3 Safe attach on 3.14+: `sys.remote_exec()` (PEP 768) as the canonical path
Rationale:
- safe, runtime-supported attach points,
- explicit security controls (`PYTHON_DISABLE_REMOTE_DEBUG`, `-X disable-remote-debug`, build-time disable),
- fits “no always-on overhead” goals.

### 3.4 Terminal-first design: layouts defined in characters, not pixels
We explicitly design for:
- **80×24** (minimum viable: compact mode),
- **120×34** (default: standard mode),
- **160×45** (wide mode).

---

## 4) Interaction model (explicit)

### 4.1 User-visible session state machine

```
DISCONNECTED
   │  (run / attach / connect)
   ▼
CONNECTING ──(fail)──► ERROR ──(retry)──► CONNECTING
   │
   ▼
RUNNING  ◄──────────────┐
   │ (breakpoint/exception/pause/step)
   ▼                      │ (continue)
PAUSED ──(disconnect)────► DISCONNECTED
   │
   ├─(restart)──► CONNECTING (new process / relaunch)
   └─(terminate)► TERMINATED
```

UI rules:
- State is always visible in the status line.
- Any transition that can fail has an explicit UX branch (with a recovery action).
- “Running vs Paused” drives which panels are live-updating and which are frozen snapshots.

### 4.2 Focus and selection model

Definitions:
- **Focus**: where keystrokes go (one widget at a time).
- **Selection**: the highlighted row/item in a list/tree.
- **Active frame**: the frame whose locals/eval context is active.
- **Cursor**: the location inside a text view (source, console input).

Rules:
- `Tab` / `Shift+Tab` cycles focus between major panes.
- `Enter` triggers the focused pane’s primary action:
  - lists/trees: open/expand/jump
  - source: “run to cursor” (paused) or “toggle breakpoint at cursor”
  - console: submit input
- `Esc` is always “cancel/close/back” (never quit).
- Focus is always obvious:
  - the focused pane gets an **accent border** (focus ring),
  - lists/tables use a consistent “selected row” highlight (dim when unfocused, bright when focused),
  - we never rely on subtle color alone (gutter markers, arrows, and header text still communicate state).

### 4.3 Command system (global + contextual)

There are two ways to do anything:
1) **Command palette** (`Ctrl+P`): global actions, fuzzy search, shows keybinding and scope.
2) **Local bindings**: the fastest path for the common loop.

All commands have:
- a stable identifier (`debug.continue`, `breakpoint.toggle`, `view.tasks.open`),
- optional keybindings (customizable),
- optional palette aliases,
- a “when” predicate (e.g., paused-only).

---

## 5) Layout system (terminal-first)

### 5.1 Layout breakpoints

**Compact (≤ 90 cols or ≤ 26 rows)** — “one main pane + tabs”
- Main pane: Source (or the last focused “main” view).
- Bottom: Console line (collapsed) + status/help.
- Right/left panes collapse into tab overlays (Stack/Locals/Watches/Breakpoints/Tasks).

**Standard (≈ 100–140 cols)** — “tri-pane”
- Left: Stack + Breakpoints (tabbed)
- Center: Source (sticky)
- Right: Locals + Watches (tabbed)
- Bottom: Console/Stdout/Transcript (tabbed, collapsible height)

**Wide (≥ 150 cols)** — “tri-pane + always-visible bottom split”
- Adds side-by-side Console and Transcript (or Console + Inspector detail).

### 5.2 “Every row earns its place”
Chrome is reduced to:
- one status line (top),
- one help/hints line (bottom),
- borders only where they communicate structure.

No pill chips, no excessive padding, no decorative UI.

### 5.3 Resizing behavior
- Layout reflows immediately on resize, preserving focus/selection.
- If a pane becomes too small to be useful, it collapses into a tab/palette action rather than truncating into illegibility.

---

## 6) Screens and panels (what exists, what it does)

### 6.1 Always-present chrome

**Top status line** (single line):
- workspace, session name, state (RUNNING/PAUSED), pid, python version, backend, active thread/frame summary.
- transient status text: “Attaching… waiting for safe point (press `!` to nudge)” or “Breakpoint pending (module not loaded)”.

**Bottom help line** (single line):
- state-specific key hints (paused vs running) + focused-pane hints.

### 6.2 Panels (primary)

**Source**
- sticky view centered on current execution line when paused
- shows breakpoint markers and current line indicator
- optional inline value previews (paused-only, capped)
- find within file (`Ctrl+F`, `/`) via an **inline bottom bar** (never covers Source)

#### Source: cursor model, run-to-cursor, and breakpoint gutter

The Source panel is the debugger’s “home”. It must be:
- **fast** (no UI stalls while rendering),
- **predictable** (cursor, selection, and execution line are never ambiguous),
- **actionable** (the next step is always one key away).

##### Cursor vs execution line (two different concepts)

We intentionally separate:
- **Execution line**: where the program is currently stopped (selected frame’s file:line).
- **Source cursor**: where the user is pointing inside Source (for “toggle breakpoint”, “run to cursor”, copy, search, etc.).

Rules:
- When the debugger *stops*, Source scrolls to the execution line and moves the cursor there.
- The user may move the cursor away (keyboard or mouse) without changing the active frame.
- Locals/Watches/Eval always use the **active frame** (not the Source cursor), so browsing Source never changes evaluation context.

This avoids the common “I scrolled and now my locals changed” confusion.

##### Execution line highlighting (must be unmistakable)

When paused, the execution line is highlighted in Source **even if Source is not focused**.
This is a deliberate choice: users frequently interact with Stack/Locals/Console while wanting
peripheral confidence about “where we are stopped”.

Rules:
- Execution highlight is rendered as a full-row background (subtle but high-contrast on dark themes).
- If the user is browsing a different file than the execution file, Source header shows: `(exec file.py:LINE)`.

##### Breakpoint gutter markers (instant visual clarity)

We show breakpoint state **in the line-number gutter**, IDE-style, without widening the layout.

Marker states (character + color semantics):
- **Bound / verified**: `●` (red) — the backend confirmed the breakpoint is active.
- **Queued / pending**: `◌` (yellow) — user requested it, but it isn’t bound *yet* (e.g., offline queue, module not loaded, or adapter not verifying).
- **Failed / rejected**: `✗` (red) — backend rejected or couldn’t place it (message explains why).
- **Execution indicator**: `▶` (green) — shows the paused execution line in the open file (in addition to the row highlight).

Display rules:
- Markers render only for the **currently open file** in Source.
- Marker rendering is lightweight and must not invalidate syntax highlighting caches unnecessarily.
- If terminal capabilities are limited (no unicode / no color), markers degrade to ASCII (`o`, `?`, `x`) and high-contrast monochrome.

##### Mouse (optional) and keyboard (primary)

Keyboard remains primary:
- `F9` / `b`: toggle breakpoint at cursor.
- `Ctrl+B`: add/toggle breakpoint by `path:line` (works even while disconnected; queues).

Mouse is an optional convenience where available:
- Click on the gutter toggles the breakpoint on that line (same semantics as `F9`).
- Mouse support must be best-effort; if a terminal doesn’t report mouse events reliably, nothing breaks.

##### Run to Cursor (the “fast loop” win)

Run to cursor is a high-leverage workflow accelerator: you visually navigate to a line and “continue until here” without manually adding/removing breakpoints.

Command:
- `debug.run_to_cursor` (palette searchable)
- keybinding: `Ctrl+F10` (global) and `Enter` (when Source is focused)

Semantics:
1) Requires a **paused** session.
2) Targets the current Source cursor’s `file:line`.
3) Implements “run to cursor” via a **temporary breakpoint**:
   - If the user already has a breakpoint on that line, yathaavat does **not** modify it.
   - Otherwise yathaavat adds a breakpoint and marks it “temporary” (implementation detail; UX can surface it later).
4) Resumes execution.
5) When the debuggee stops at the target line, yathaavat removes the temporary breakpoint (if it created it).

Important behavior notes:
- If execution stops at another breakpoint first, “run to cursor” remains pending (the temporary breakpoint stays armed). This matches common debugger behavior and keeps the model simple and reliable.
- A later v2 polish can add “ignore other breakpoints while running-to-cursor” as an opt-in mode, but the default should respect user breakpoints.

Performance constraints:
- Adding/removing the temporary breakpoint must be O(1) on the UI thread; DAP calls happen off-thread/async.
- No “wait forever”: UI must remain responsive even if the target line is never reached (infinite loop, different code path, etc.).

##### Inline find (Source) — terminal-first UX

`Ctrl+F` (or `/`) opens a **compact, inline Find bar** docked at the bottom of Source.
This is intentional: it preserves context and keeps the code visible while searching.

Interaction rules:
- typing updates the query and (debounced) jumps to the next match,
- `Enter` / `F3` finds next match, `Shift+Enter` / `Shift+F3` finds previous,
- match position is shown as `line:col`,
- `Esc` closes find and returns focus to Source.

##### Source navigation: Find + Go to line

Debugging often requires scanning unfamiliar code quickly. Source supports lightweight, keyboard-first navigation:
- **Find** (`Ctrl+F`): jump to next match (wraps around). Highlight the match selection and update the Source cursor location.
- **Find previous** (`Shift+Enter` while Find is focused): jump to the previous match (wraps around).
- **Go to line** (`Ctrl+G`): jump to `line[:col]` in the currently open Source file.

Design notes:
- **Find** is implemented as a compact bottom overlay that keeps Source visible while searching (so you can confirm context while iterating matches).
- Future v2 polish can add match counts and highlight-all, but the default remains minimal and snappy.

**Stack**
- thread selector (if multiple threads), surfaced as a **Threads** tab/pane
- frames list with file:line + function + locals summary preview
- frame pinning (keep active frame while browsing other frames)

**Locals / Globals**
- preview-first variable list: `name`, `type`, `value preview`, `len/size` when applicable
- expands lazily; uses paging if backend supports it

**Watches**
- watch list with last value + change indicator
- evaluation is paused-only by default; “live watch” requires explicit opt-in and shows a warning
- quick add (`Ctrl+W`) and simple management (delete/copy) from the Watches panel

**Breakpoints**
- list with verification state: bound/unverified/error
- edit: condition, hit count, log message
- per-breakpoint “why unverified” explanation if available

#### Breakpoints: configure vs toggle (conditions, hit counts, logpoints)

Breakpoints are “first-class” objects in v2:
- **Toggle** breakpoints are the fast path (single key, no prompts).
- **Configured** breakpoints are the power path (conditions, hit counts, logpoints), but still ergonomic.

##### The three configuration fields

All fields map directly onto DAP `setBreakpoints` request fields:
- **Condition** (`condition`): Python expression evaluated at the breakpoint site.
  - If falsey, the breakpoint does not trigger.
  - Adapter-defined: expression language, scope, and error behavior are backend-specific.
- **Hit condition** (`hitCondition`): adapter-defined “stop on the Nth hit” behavior.
  - Typically supports numeric values (`3`) and, in some adapters, comparators (`>=3`).
- **Log message** (`logMessage`): makes the breakpoint a **logpoint**.
  - Instead of pausing, the adapter emits an output event (captured in Transcript).
  - Supports adapter-defined expression interpolation (often `{expr}`).

##### UX: adding and editing configured breakpoints

Fast creation flows:
- `F9` / `b` / gutter click: **toggle** breakpoint at Source cursor.
- `Ctrl+B`: **Add breakpoint…** dialog:
  - accepts `path:line` or `path#Lline` or just `line` (uses current Source file),
  - optional config tokens:
    - `if EXPR`
    - `hit N`
    - `log MSG`
  - tokens with spaces are quoted (shell-style parsing).

Examples:
- `app/service.py:120`
- `app/service.py:120 if "user.is_admin"`
- `app/service.py:120 hit 3`
- `app/service.py:120 log "order={order.id} total={total}"`

Editing flows:
- Breakpoints panel shows configuration in the “Message” column (`log … • if … • hit …`).
- `e` on a breakpoint row opens an inline editor (bottom overlay) to update/clear fields.

##### Offline queueing (disconnected workflows)

Breakpoints can be created while disconnected and are **queued**:
- The UI shows them immediately (and Source gutter markers update when viewing that file).
- On connect/launch, yathaavat applies all queued breakpoints via DAP.
- Verification state transitions from “queued/pending” → “verified” or “error”, and the gutter updates.

This keeps workflows frictionless: you can prepare breakpoints before connecting to a long-running process.

**Console**
- input: multiline, history, completion (best-effort), safe paste
- output: structured (stdout/stderr/debugger output separated)

**Transcript**
- append-only timeline: user commands + backend events + stdout/stderr
- export: markdown + jsonl
- “bookmark” events (“this was the weird stop”)

### 6.3 Panels (advanced)

**Exceptions**
- exception details + traceback + ExceptionGroup tree rendering
- quick actions: copy traceback, open failing frame, add breakpoint at raise site

**Tasks (async)**
- list/tree view (state: RUNNING/AWAIT/SLEEP/BLOCKED)
- “jump to await point” best-effort: navigates to awaited frame/coroutine when available

**Threads**
- per-thread state + top frame preview
- lock hints if available (backend-dependent)

**Process tree**
- shows debuggee + subprocesses (when backend supports)
- clear boundary markers: “debugging this process” vs “observed only”

**Settings**
- keymap editor (view/edit effective bindings)
- theming (truecolor/256-color/ascii modes)
- safe attach policy settings

**Help**
- contextual help (`?`), plus “Debugging 101” for first-run

---

## 7) Backend strategy (v2)

### 7.1 Backend types

**(A) DAP backend (default)**: `debugpy`
- immediate compatibility wins
- works across OSes and across many deployment styles

**(B) Native 3.14+ backend (planned track)**: “yathaavat-agent”
- leverages `sys.monitoring` for lower overhead stepping (future)
- injected via `sys.remote_exec` without unsafe native injection
- speaks DAP (preferred) or a small custom protocol (fallback)

v2 designs the architecture to support (B) without rewriting the UI.

### 7.2 DAP client design (must be correct and fast)

Core rules (from DAP realities):
- Treat each `stopped` event as a **snapshot boundary**: refetch threads/stack/scopes and invalidate variable trees.
- Implement **variable paging** (`start`/`count`) when `supportsVariablePaging` is true.
- Represent breakpoint verification states explicitly (verified/unverified/message).

Source reference:
- DAP spec (variables paging): https://microsoft.github.io/debug-adapter-protocol/specification

---

## 8) Safe attach (Python 3.14+): production-grade design

### 8.1 What safe attach *is* (and isn’t)

Safe attach uses `sys.remote_exec(pid, script_path)` to schedule a Python script to execute in the target’s main thread at the next safe evaluation point. This avoids unsafe native-code injection techniques.

Constraints:
- no completion signal from `remote_exec`,
- attach may be delayed if the target is blocked in I/O or native code,
- elevated privileges are commonly required (ptrace/admin),
- remote debugging can be disabled by policy.

Source reference:
- Python remote debugging HOWTO: https://docs.python.org/3.14/howto/remote_debugging.html

### 8.2 Attach handshake protocol (yathaavat-specific)

Because `remote_exec()` returns immediately, yathaavat defines a handshake:

1. yathaavat creates a temp directory (shared FS) with:
   - `bootstrap.py` (the injected script)
   - `handshake.json` (written by the target on success or failure)
2. `bootstrap.py` runs in the target and:
   - records basic identity: pid, python version, timestamp
   - attempts to start the chosen backend (initially debugpy listener on loopback)
   - writes `{ status: \"ready\", endpoint: \"127.0.0.1:PORT\", token: ... }` on success
   - writes `{ status: \"error\", error: ... }` on failure
3. yathaavat polls `handshake.json` with a tight backoff budget and a clear UI:
   - “waiting for safe point” with elapsed time
   - optional “nudge” action (send a signal) where safe and supported
4. once ready, yathaavat connects via DAP to the provided endpoint.

Why file-based?
- works cross-platform with minimal assumptions,
- avoids relying on debugpy supporting exotic transports,
- makes failure observable and debuggable.

### 8.3 Security posture and policies

Defaults:
- listen on **loopback only** (`127.0.0.1`)
- require explicit confirmation to bind to non-loopback
- never enable remote debug on the target if policy forbids it

Policy knobs:
- `safe_attach.policy = never | prompt | always`
- `listen.address = 127.0.0.1 | ::1 | 0.0.0.0` (non-loopback prompts)
- `safe_attach.timeout_ms` (e.g., 8000ms default)

### 8.4 Failure UX (must be actionable)

When safe attach fails, the UI surfaces:
- reason category: permissions / remote debug disabled / version mismatch / missing dependency / target not Python
- concrete remediation (platform-specific):
  - Linux ptrace_scope guidance
  - macOS “run with sudo” guidance
  - Windows admin/SeDebugPrivilege guidance

---

## 9) Performance budgets and rules

### 9.1 Latency budgets (targets)
- Keystroke → paint: **≤ 30ms** median, **≤ 80ms** p95
- Pause event → “usable UI” (source line + stack): **≤ 150ms** median
- Open variable expansion (first preview): **≤ 50ms** median
- Search/filter list: **≤ 30ms** per update (incremental)

### 9.2 Hard rules
- Never block the UI thread on network or large formatting.
- Never render unbounded lists without virtualization.
- Never repeatedly evaluate expressions in a tight loop without explicit user opt-in.

### 9.3 Virtualization strategy (required)
- Variables, stack frames, tasks, transcript: render only visible rows.
- Prefer backend paging (DAP `start`/`count`) when available.
- For non-paged backends, implement local paging and “load more” affordances.

### 9.4 Rendering strategy
- Preview-first rendering (type + short value).
- Truncation policy is explicit and visible (e.g., `… (truncated, press Enter for more)`).
- Expensive repr is time-boxed and cancellable.

---

## 10) Terminal compatibility and fallbacks

### 10.1 Capability detection
Detect and adapt:
- truecolor vs 256-color
- mouse reporting
- kitty keyboard protocol availability (enables richer keymaps)
- unicode width quirks

### 10.2 “ASCII mode”
Provide `--ascii` and config:
- replaces box drawing with `+|-`
- avoids ambiguous glyphs
- reduces styling to maximize portability

### 10.3 Mouse as optional
Mouse is a convenience (click to focus, scroll, toggle breakpoint), never required.

Reference:
- Terminal protocol notes: `docs/research/03_terminal_capabilities.md`

---

## 11) Persistence and transcript-first design

Persist per-workspace:
- breakpoints, watches
- layout choice + pane sizes
- theme + color mode
- keymap overrides

Transcript:
- JSONL stream of user commands + DAP events + outputs with timestamps
- export bundle includes:
  - transcript.jsonl
  - transcript.md (human)
  - capabilities summary (adapter)
  - terminal capabilities snapshot

Support bundle:
- `yathaavat doctor --bundle out.zip` zips redacted config + logs + transcript excerpts.

---

## 12) Extensibility (“moldable debugging”)

Plugin goals:
- allow domain-specific panels and renderers without forking yathaavat.

Plugin types:
- **renderers**: custom object renderers (dataclasses, pandas, ORMs, exception groups)
- **panels**: new views (e.g., SQL queries, HTTP request inspector)
- **commands**: add palette actions and keybindings
- **exception lenses**: exception-type-driven contextual UI (inspired by “moldable exceptions”)
- **backends**: alternative debug adapters (DAP or native)

Distribution:
- Python entry points + versioned plugin API.

Research reference:
- `docs/research/05_debugging_ux_literature_2024_2025.md` (Moldable Exceptions)

---

## 13) Implementation plan (v2-aligned milestones)

**M0 Skeleton**
- CLI + Textual shell with layout breakpoints (compact/standard/wide)
- command palette + help overlay
- transcript infrastructure (JSONL) + export

**M1 DAP MVP (debugpy)**
- run/connect/attach-to-endpoint
- breakpoints + stepping + stack + variables + eval
- variable paging + virtualization

**M2 Production UX**
- breakpoint verification UX + editor (conditions/logpoints)
- reconnect flows + error states
- “doctor bundle”

**M3 Safe attach (3.14+)**
- `sys.remote_exec` handshake protocol
- policy controls + permission troubleshooting UX
- secure defaults (loopback bind)

**M4 Concurrency clarity**
- threads view + tasks view (best-effort via backend)
- exception groups view

**M5 Extensibility**
- plugin API for renderers/panels/commands
- example “exception lens” plugin

**M6 Polish**
- keymap editor and presets (default/vim)
- theming + accessibility
- crash resilience, support bundle quality

---

## Appendix: Research map

See `docs/research/README.md` for the full set of notes that informed this redesign.
