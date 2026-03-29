# Current State Review (v0.2) — Gaps & Opportunities

Last updated: 2025-12-20

This note audits `docs/DESIGN.md` and `docs/mocks.html` to surface gaps, risks, and concrete improvement opportunities to carry into v2.

---

## What v0.2 already gets right

- **Clear north star**: “daily-driver” debugger, keyboard-first, safe attach, low latency, transcript-first.
- **Solid baseline architecture**: Textual UI + debugger backend via **DAP** (debugpy) keeps UI and backend swappable.
- **Reasonable feature decomposition**: MVP fundamentals first; then watches, exceptions, async/task views, safe attach.
- **Good taste in affordances**: command palette, contextual help (`?`), “idiot-proofing”, and a “doctor bundle”.
- **Sanskrit labeling**: “optional, never required” is the correct posture for themed language overlays.

---

## Design doc gaps (what’s missing or underspecified)

### 1) Interaction model is too high-level
- No explicit **focus model**: how focus moves, how selection vs. cursor vs. active frame is represented, what “enter” does per panel.
- No **modal/state machine** diagram for user-visible states: `disconnected → connecting → running ↔ paused → terminated`, plus error/reconnect branches.
- No “**single source of truth**” for navigation: is the palette primary, or are views primary with local keymaps?

### 2) DAP reality & debugpy quirks are not accounted for
- No detailed mapping between **DAP events/requests** and UI state (threads/stack/variables refresh cadence; scopes/variable paging).
- No handling plan for **unverified/pending breakpoints**, path mapping, and source-availability issues (remote hosts, vendored libs, zipapps).
- No plan for **multi-process** debugging boundaries (debugpy’s subprocess attach and how to visualize process trees without confusing users).

### 3) Performance targets are aspirational, not enforceable
- No explicit **latency budgets** (keystroke → paint; pause → full UI hydrate; search results; variable expansion).
- No strategy for **virtualization** in large lists (variables, stack frames, tasks, logs) beyond “lazy/paginated”.
- No “safe repr” envelope (timeouts, truncation policy, side-effect avoidance) beyond basic caps.

### 4) Terminal constraints are not designed-in
- No responsive layout strategy for **80×24**, **100×30**, **120×34**, etc. (v0.2 assumes a roomy 3-column layout).
- No explicit fallback behavior for:
  - limited colors (no truecolor)
  - limited Unicode width/emoji
  - no mouse reporting
  - slow terminals / high-latency redraw

### 5) Safe attach needs a production-grade handshake design
`sys.remote_exec()` exists in 3.14+, but v0.2 doesn’t specify:
- how we confirm the injected script ran (remote_exec returns immediately; no completion signal),
- how we avoid port races if the target must open a listener,
- how we handle remote-debug being disabled (`PYTHON_DISABLE_REMOTE_DEBUG`, `-X disable-remote-debug`, `--without-remote-debug`),
- permission guidance (ptrace / admin) and the UX when it fails.

---

## Mocks gaps (what breaks under real terminal constraints)

### 1) Layout is “web roomy”, not “terminal tight”
- Large padding, rounded corners, pill chips: aesthetically nice in HTML, but doesn’t translate to **character-cell economics**.
- Uses fixed pixel dimensions; doesn’t show behavior for **narrow** terminals or aggressive resizing.

### 2) Missing critical screens
- Attach/run wizard with capability detection and warnings.
- Command palette overlay and search flows.
- Breakpoints editor (conditions, hit counts, logpoints).
- Exceptions (including ExceptionGroup tree).
- Disconnected/reconnect UI and failure modes.
- Object inspector paging and “expand/preview” mechanics.

### 3) Focus/selection and “what happens next” are ambiguous
- Mocks don’t clearly show the active focus target, selection, and which keys act globally vs. locally.

---

## Highest leverage opportunities for v2

1. **Define a strict interaction model**: state machine + focus model + consistent global commands.
2. **Design for terminal sizes first**: ship a compact default that scales up, not a spacious layout that scales down.
3. **Make safe attach real**: explicit handshake protocol + capability probes + failure UX.
4. **Bake in DAP reality**: event refresh strategy, paging, breakpoint verification, path mapping, and multi-process boundaries.
5. **Quantify performance**: set budgets and “never block UI” rules, then design caching/virtualization around them.

