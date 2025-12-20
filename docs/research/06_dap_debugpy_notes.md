# DAP + debugpy Notes (Client Implications for a TUI)

Last updated: 2025-12-20

This note captures DAP behaviors that directly shape yathaavat’s architecture and UX, plus debugpy-specific considerations.

---

## 1) DAP basics that matter to UI correctness

### Object lifetimes and refresh
Many DAP IDs are only valid in the current paused state:
- thread IDs and frame IDs are generally stable within a stop,
- **variable references** (`variablesReference`) typically require the debuggee to be paused, and may become invalid after resume/step.

**UI implication**: treat pause as a snapshot boundary. On every stop:
- refetch threads → stack → scopes,
- invalidate cached variable nodes unless explicitly guaranteed by the adapter.

### Event-driven state machine
Key events for the session timeline:
- `stopped` (reason: breakpoint/exception/step/pause/etc.)
- `continued`
- `output` (stdout/stderr/console)
- `terminated` / `exited`
- `thread` (started/exited) in some adapters

**UI implication**: visible “state” must be driven by events, not assumptions (e.g. always show RUNNING/PAUSED/DISCONNECTED).

Source:
- DAP specification: https://microsoft.github.io/debug-adapter-protocol/specification

---

## 2) Variables: paging, formatting, and virtualization

DAP supports **variable paging**:
- `variables` request accepts `start` and `count` if `supportsVariablePaging` is true.
- `filter` can request only `named` or only `indexed` children.

**UI implication**: a performant inspector should:
- show a preview row immediately (type/value/len),
- fetch children lazily,
- page indexed children for large lists/dicts,
- keep rendering work proportional to what’s visible in the viewport.

Source:
- DAP `variables` request (`start`/`count`): https://microsoft.github.io/debug-adapter-protocol/specification

---

## 3) Breakpoints: “pending is normal”

DAP breakpoints often have “verification” semantics:
- the adapter can accept a breakpoint but mark it unverified if it can’t bind yet (e.g., module not loaded, path mismatch).

**UI implication**:
- treat “unverified” as first-class state, not an error,
- surface *why* if provided (message), and show a remediation hint (path mapping, ensure module import, etc.).

Source:
- DAP `setBreakpoints` response schema (verified/message): https://microsoft.github.io/debug-adapter-protocol/specification

---

## 4) Evaluation is a product surface (and a risk surface)

The DAP `evaluate` request is powerful but dangerous:
- expressions can be slow,
- can have side effects,
- can raise exceptions.

UI implications:
- default to “preview-first” evaluation in the inspector (avoid re-evaluating side-effectful expressions repeatedly),
- make evaluation scope explicit (frame),
- provide copyable errors and a way to view full tracebacks.

---

## 5) debugpy specifics (from its public README)

Relevant behaviors:
- `debugpy --listen` controls which interface is bound; binding `0.0.0.0` enables remote attach but is dangerous (arbitrary code execution risk).
- `debugpy --pid <pid>` exists as an attach-by-PID workflow.

Yathaavat implication:
- for CPython 3.14+, use PEP 768 safe attach as the canonical “PID attach” mechanism (start debugpy inside the target via `sys.remote_exec`),
- provide strong guardrails for any non-loopback bind.

Source:
- debugpy README: https://raw.githubusercontent.com/microsoft/debugpy/main/README.md

