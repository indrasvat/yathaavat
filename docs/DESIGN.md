# yathaavat — Design Doc (Python 3.14+ TUI Visual Debugger)

**Doc version:** v0.2 (generated 2025-12-19 23:05:16 UTC-08:00-0800)  
**Target:** Python **3.14+** (CPython) • macOS/Linux first, Windows where feasible  
**North star:** A *daily-driver* terminal debugger: fast, keyboard-first, safe attach, and delightful.

---

## 0) Active session log (agent-maintained)

> **Instructions for agents:** keep this section updated *as you work*. Add a new row at each meaningful change (start/finish a task, unblock, ship a milestone). Use local time.

| Time (local) | State | What changed | Next actions | Blockers |
|---|---|---|---|---|
| 2025-12-19 23:05:16 UTC-08:00-0800 | INIT | Generated v0.2 design doc + mocks for **yathaavat** | Scaffold repo; implement MVP DAP session engine | None |

### Milestones checklist (agent-maintained)

- [ ] M0 Repo scaffold + CI + demo app launches
- [ ] M1 MVP: Launch/Attach, breakpoints, step, stack, locals, eval, transcript
- [ ] M2 Watches, exceptions (incl. exception groups), search, palette polish
- [ ] M3 Safe production attach via Python 3.14 external attach (`sys.remote_exec`)
- [ ] M4 Async/Threads/Process tree panels; hang investigation UX
- [ ] M5 Plugin SDK + docs + examples (renderers/panels)
- [ ] M6 Polish: theming, accessibility, crash resilience, support bundle

---

## 1) Product summary

**yathaavat** is a **Textual** TUI debugger client for Python 3.14+ that speaks **DAP (Debug Adapter Protocol)** to a debug backend (default: `debugpy`). It prioritizes *forgiving UX*, *keyboard speed*, and modern concurrency (asyncio/tasks/threads). For Python 3.14+, it adds a “safe attach” pathway that can attach to a running PID using the runtime’s supported external attach facility, then bootstrap a DAP endpoint inside the target.

---

## 2) Goals and non-goals

### Goals
1. **Daily-driver UX**: source + stack + variables + console + breakpoints + watches in one place.
2. **Keyboard-first**: command palette, fuzzy navigation, single-key stepping mode.
3. **Safe attach** for long-running processes (prod-friendly defaults).
4. **Async clarity**: tasks/tree views and “jump to await point”.
5. **Low-latency UI** on large objects and big codebases (lazy, paginated inspection).
6. **Extensible**: plugins for panels, renderers, and commands.
7. **Idiotic-proof**: wizards, guardrails, excellent errors, self-healing defaults.

### Non-goals (v1)
- Full IDE replacement
- Building a new debug server from scratch (start with `debugpy`)
- Full record/replay time-travel debugging (v1 does snapshots + transcript)

---

## 3) Why Python 3.14+ (practical power-ups)

yathaavat targets 3.14+ to unlock attach and introspection workflows that are either impossible or far messier on older runtimes:

- **Safe external attach**: attach to a running process using the runtime-supported mechanism (no always-on overhead).
- **Async introspection** improvements: better task/process visibility for asyncio-heavy services.
- **Runtime introspection hooks**: leverage modern `sys.monitoring`/introspection to improve stepping and event capture.

> **Agent note:** keep this section aligned with the *current* 3.14 docs during implementation.

---

## 4) Target users and golden workflows

### Personas
- SSH-first backend engineer debugging services and workers
- CLI/tool author iterating on scripts
- SRE investigating stuck processes (hangs, deadlocks, overload)
- Library author debugging exception groups and complex data

### Golden workflows (must be one command)
1. Launch + debug: `yathaavat run python -m myapp ...`
2. Attach to PID (dev): `yathaavat attach --pid 1234`
3. Safe attach (3.14+): `yathaavat attach --pid 1234 --safe-attach`
4. Debug tests: `yathaavat test -k test_name`
5. Debug a hang: open **Tasks** view → tree → jump to await point
6. Post-mortem: open transcript bundle in offline viewer

---

## 5) Core feature requirements

### 5.1 Session lifecycle
- Launch (script/module), attach (PID), connect (host:port / unix socket)
- Multiple sessions (tabs); one active
- Persist:
  - breakpoints and watches per workspace
  - layout + theme + keymap
  - session transcript (commands + outputs + timestamps)

### 5.2 Debugging fundamentals (MVP)
- Breakpoints:
  - line, conditional, hit-count
  - logpoints (print message without stopping)
- Execution:
  - continue/pause, step-in/over/out, run-to-cursor
  - restart (for launched targets)
- Stack + frames:
  - call stack view, switch frame, show locals/globals/closure vars
- Watches:
  - expression watch list; pin watches per frame
- Evaluate:
  - debug console with history, multiline, pretty output, safe truncation

### 5.3 Modern Python needs
- Asyncio tasks view (list + tree), coroutine stacks, awaited-by relationships (best-effort)
- Threads view (per-thread stack; lock hints if available)
- Subprocess/multiprocess (process tree, attach where supported)
- Exception groups (`except*`) tree rendering + navigation
- Type-aware inspection (runtime type + optional hints)
- Large object browsing:
  - lazy expansion; paging; custom renderers
- Source navigation:
  - fuzzy file switcher; “jump to current line”; search within file

### 5.4 Logging/export (must)
- **Transcript**: every action + event logged with timestamps
- Export:
  - Markdown (human)
  - JSONL (machine, event-per-line)
- Support bundle: `doctor --bundle` zips config (redacted), logs, capabilities

---

## 6) UX principles (idiot-proofing)

### 6.1 First-run wizard
- detect terminal (truecolor/mouse/kitty)
- detect python env (uv/venv/pyenv/conda)
- offer: Run / Attach PID / Connect
- if attach:
  - probe target; show “what’s possible”
  - if safe attach unavailable: show exact remediation path

### 6.2 Recoverable mistakes
- unbound breakpoint → show “pending” with reason
- eval failure → inline error, “copy traceback”
- disconnect → reconnect/restart options; save transcript safely

### 6.3 Discoverability
- command palette (fuzzy) shows keys + Sanskrit tags (optional)
- contextual help overlay (`?`) for the focused panel
- “Debugging 101” built-in cheat sheet

---

## 7) UI layout (default)

- **Top bar**: session, state, PID, python version, connection
- **Left**: files/breakpoints (tabbed)
- **Center**: source view with current line highlight + optional inline previews
- **Right**: variables (locals/globals/watches tabbed)
- **Bottom**: console/stdout/transcript (tabbed)

Panels list:
- Source • Stack • Variables • Watches • Breakpoints • Threads • Tasks • Exceptions • Transcript • Settings • Help

---

## 8) Keyboard support (modern, complete, customizable)

### 8.1 Global
- `Ctrl+P` palette
- `Ctrl+K` fuzzy file/symbol search
- `Ctrl+J` jump to current execution line
- `Ctrl+L` transcript/log
- `Tab` next pane, `Shift+Tab` prev pane
- `/` search within current view
- `?` contextual help
- `Esc` cancel/close/back

### 8.2 Debug controls (+ Sanskrit tags, middle-ground)
- `F5` / `c` — continue *(anuvartan)*
- `p` — pause *(viraam)*
- `Shift+F5` — stop *(samaapti)*
- `F9` / `b` — toggle breakpoint *(bindu)*
- `F10` / `n` — step over *(atikram)*
- `F11` / `s` — step in *(pravesh)*
- `Shift+F11` / `f` — step out *(nirgam)*
- `Ctrl+F10` — run to cursor *(lakshya-gaman)*
- `Ctrl+Enter` — evaluate selection *(moolyaankan)*

### 8.3 Optional “vim mode”
- `hjkl`, `gg/G`, `]b/[b` breakpoints, `]f/[f` frames

### 8.4 Keymap config
- TOML config; show effective keymap: `yathaavat keys`
- detect and warn on conflicts

---

## 9) Command language and Sanskrit labels (reasonable middle ground)

**Default principle:** English is the canonical command surface; Sanskrit is a **small, stable tag vocabulary** that adds theme without confusing users.

### 9.1 Defaults
- CLI stays English: `yathaavat run|attach|connect|test|doctor|export|keys`
- UI shows Sanskrit tags as badges (configurable density)

### 9.2 Optional modes
- `--labels sa` (or config): show tags more prominently
- `--aliases sa`: enable small Sanskrit aliases (never required)

### 9.3 Canonical mini-lexicon (stable)

#### Core actions
| Action | English | Sanskrit tag | ASCII |
|---|---|---|---|
| Continue/Resume | continue | अनुवर्तन | anuvartan |
| Pause | pause | विराम | viraam |
| Stop | stop | समाप्ति | samaapti |
| Step In | step-in | प्रवेश | pravesh |
| Step Over | step-over | अतिक्रम | atikram |
| Step Out | step-out | निर्गम | nirgam |
| Run to Cursor | run-to-cursor | लक्ष्य-गमन | lakshya-gaman |
| Evaluate | eval | मूल्यांकन | moolyaankan |

#### Debugger nouns
| Concept | Sanskrit term | ASCII |
|---|---|---|
| Breakpoint | बिन्दु (or विराम-बिन्दु) | bindu / viraam-bindu |
| Watch | प्रेक्षा | prekshaa |
| Stack | क्रम | kram |
| Frame | आवरण | aavaran |
| Thread | सूत्र | sootr |
| Task | कार्य | kaarya |
| Exception | अपवाद | apavaad |
| Transcript | वृत्तान्त | vrittaant |

#### Optional Sanskrit CLI aliases (`--aliases sa`)
| English cmd | Sanskrit alias | ASCII |
|---|---|---|
| run | प्रारम्भ | praarambh |
| attach | बन्ध | bandh |
| connect | योग | yog |
| test | परीक्षा | parikshaa |
| doctor | निदान | nidaan |
| export | निर्यात | niryaat |
| keys | कुञ्जिका | kunjikaa |

---

## 10) Architecture

### 10.1 High-level
```
┌──────────────────────────┐
│     yathaavat TUI (Textual)│
└─────────────┬────────────┘
              │ intents/events
┌─────────────▼────────────┐
│     Session Orchestrator  │  state machine, persistence, routing
└─────────────┬────────────┘
              │ debugger-agnostic API
┌─────────────▼────────────┐
│       Debug Transport     │  DAP client + safe-attach bootstrap
└─────────────┬────────────┘
              │
        ┌─────▼─────┐
        │  debugpy   │  default DAP server
        └────────────┘
```

### 10.2 Why DAP-first
- DAP is the common denominator across modern debuggers (Go, Node, etc.).
- Keeps backend swappable; lets UI innovate without rewriting debug logic.

### 10.3 Suggested package layout
```
yathaavat/
  cli.py
  app/
    tui.py
    theme.tcss
    commands.py
    widgets/...
  core/
    session.py
    models.py
    persistence.py
    transcript.py
    timeline.py
    plugins.py
  debug/
    dap/
      client.py
      protocol.py
      adapters.py
    attach/
      safe_attach.py
      pid_probe.py
  util/
    fuzzy.py
    formatters.py
    logging.py
```

### 10.4 Concurrency
- UI: Textual asyncio loop
- DAP client: async message pump task
- heavy work (indexing/formatting huge objects): background executor or subinterpreters where useful

---

## 11) Debug backend strategy

### 11.1 Default: debugpy via DAP
- Launch: run python with debugpy listening on loopback/unix socket
- Attach: connect to existing debugpy endpoint

### 11.2 Safe attach (3.14+)
**Goal:** attach to PID using supported external attach, then start a local-only debugpy listener in-process, then connect over DAP.

**UX guardrails:**
- default to loopback/unix socket
- warnings when binding beyond localhost
- explicit policy toggles in config (never/prompt/always)

### 11.3 Fallbacks
If safe attach isn’t possible:
- attach to a pre-existing endpoint
- offer exact relaunch command that adds debugpy (copy-paste)

---

## 12) Data model (core state)

Entities:
- Workspace, Session, Thread, Frame, Variable, Breakpoint, Watch, Task, ExceptionGroup
- Timeline snapshots: captured on each pause (limited depth + preview-only)

Snapshots capture:
- active thread + top frames
- locals previews
- watches
- exception info

Store in a ring buffer (e.g., last 200 stops), exportable.

---

## 13) Object inspection (fast + safe)

- Preview-first: type + short value + size/len
- Lazy expansion + paging
- Renderer selection:
  1) user override
  2) plugin renderer
  3) built-in renderers (dataclass/mapping/sequence/exceptions)
  4) safe repr fallback

Safety rules:
- cap recursion depth
- cap render time (timeouts) for expensive `repr`
- never crash UI on odd objects

---

## 14) Transcript + diagnostics

### 14.1 Transcript
Captured with timestamps:
- user commands
- DAP events (stopped/continued/output)
- stdout/stderr where available
- tool warnings/errors

Formats:
- `transcript.md`
- `transcript.jsonl`

### 14.2 Doctor bundle
`yathaavat doctor --bundle out.zip` includes:
- redacted config
- keymap
- terminal capabilities
- recent logs
- adapter capabilities summary

---

## 15) TUI mocks (HTML)

These mocks model layout, density, and hierarchy.  
See: `mocks.html` in this bundle.

---

## 16) Testing strategy

- Unit: protocol parsing, state machine, keymap, transcript
- Integration: launch a sample target and drive a scripted DAP session headlessly
- Manual: resize, reconnect, async hang, big objects, attach policies

---

## 17) Implementation plan (agent-ready)

### M0 Scaffold
- uv/pyproject, ruff, pyright/mypy, pytest, CI
- minimal Textual app with panes + palette stub

### M1 DAP MVP
- DAP transport + message pump
- `run` + `connect`
- breakpoints + stepping + stack + variables + eval
- transcript capture + export

### M2 UX Power
- watches UI
- exceptions (incl. groups)
- fuzzy file switcher
- robust reconnect UX

### M3 Safe attach
- pid probe and capability detection
- bootstrap script for in-process debug endpoint
- hard guardrails + policy UX
- docs for prod-safe usage

### M4 Concurrency views
- threads view
- tasks view (list + tree)
- process tree + attach to children where possible

### M5 Plugins
- entrypoints plugin manager
- example renderer plugins
- plugin docs/templates

### M6 Polish
- themes, accessibility, keymap editor
- “doctor” bundle polish
- release packaging

---

## 18) CLI specification (agent-ready)

**Principle:** CLI must be usable without the TUI (automation/agents). The TUI is a presentation layer over the same session engine.

### 18.1 Commands (English canonical)
- `yathaavat run [--] <python args...>`
- `yathaavat attach --pid <pid> [--safe-attach] [--endpoint ...]`
- `yathaavat connect <host:port|unix:path>`
- `yathaavat test [pytest args...]`
- `yathaavat doctor [--bundle <zip>]`
- `yathaavat export <bundle>`
- `yathaavat keys`

### 18.2 Optional Sanskrit aliases (`--aliases sa`)
- `praarambh` (run), `bandh` (attach), `yog` (connect), `parikshaa` (test), `nidaan` (doctor), `niryaat` (export), `kunjikaa` (keys)

### 18.3 Exit codes
- `0` success
- `2` invalid args/config
- `3` cannot connect / adapter init failed
- `4` attach denied by policy/security
- `5` target crashed during launch
- `130` interrupted

---

## 19) Appendix: UX inspirations worth borrowing
- single-key stepping modes (speed)
- transcript-first debugging (shareable, incident-friendly)
- snapshot “timeline” (lite post-mortem navigation)

