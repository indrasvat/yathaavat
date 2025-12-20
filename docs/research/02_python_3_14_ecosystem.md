# Python 3.14+ Ecosystem Notes (Debugger-Relevant)

Last updated: 2025-12-20 (validated against Python 3.14.2 docs / runtime)

This note focuses on Python 3.14+ runtime features that materially change what a “production-ready” debugger can do, plus typing/runtime introspection changes that influence yathaavat’s implementation and UX.

---

## 1) PEP 768: Safe external debugger interface (`sys.remote_exec`)

### What it enables
Python 3.14 adds a **runtime-supported**, “safe points” mechanism for **attaching debuggers/profilers** to a running CPython process *without always-on overhead*.

At the user-facing level:
- `sys.remote_exec(pid, script_path)` schedules a Python source file to be executed in the **target process’s main thread** at the **next safe evaluation point** and **returns immediately** (no completion signal).
- `python -m pdb -p <pid>` uses this feature to attach a pdb session to a running process.

### Key semantics (important constraints for yathaavat’s safe attach UX)
- **No completion/ack channel**: the caller cannot directly know when/if the script executed.
- **Delayed execution**: if the process is blocked in I/O/syscall or running long native code, attach may not “take” until the interpreter reaches a safe point (or receives a signal).
- **Script file lifetime**: caller must ensure the script path remains readable and isn’t overwritten before the target reads it.
- **Version matching**: local and remote interpreters must share **major/minor**; if either side is pre-release then versions must match exactly.
- **Security controls**:
  - `PYTHON_DISABLE_REMOTE_DEBUG` disables both sending and receiving remote debug scripts.
  - `-X disable-remote-debug` does the same.
  - `--without-remote-debug` can disable the feature at build time.
- **Audit hooks**:
  - `sys.remote_exec` auditing event is raised in the calling process.
  - `cpython.remote_debugger_script` auditing event is raised in the target process.

### Permission reality (why attach must be “guided”)
Python’s HOWTO explicitly calls out elevated privileges on most platforms:
- Linux: ptrace restrictions, CAP_SYS_PTRACE, Yama hardening, container flags.
- macOS: may require `sudo` even for same-user attaches due to system security.
- Windows: admin rights / `SeDebugPrivilege` in some cases.

Sources:
- `sys.remote_exec()` docs: https://docs.python.org/3.14/library/sys.html#sys.remote_exec
- Remote debugging attachment protocol (permission requirements + protocol): https://docs.python.org/3.14/howto/remote_debugging.html
- PEP 768 (historical, with background and security rationale): https://peps.python.org/pep-0768/
- Disabling remote debug env var: https://docs.python.org/3.14/using/cmdline.html#envvar-PYTHON_DISABLE_REMOTE_DEBUG

---

## 2) `pdb` in 3.14: remote attach and async improvements

Debugger UX improvements in 3.14 that are good signals for yathaavat:
- **Remote attach by PID**: `python -m pdb -p <pid>` (builds on PEP 768).
- **Async debugging affordances**: `pdb.set_trace_async()` and `$_asynctask` (from the 3.14 changelog).
- **Input ergonomics**: auto-indent for multiline input; syntax-highlighted source output.

Sources:
- What’s New (pdb + PEP 768): https://docs.python.org/3.14/whatsnew/3.14.html
- `pdb` CLI option docs: https://docs.python.org/3.14/library/pdb.html

---

## 3) `sys.monitoring`: low-overhead events (PEP 669 lineage)

### Why this matters even if yathaavat starts DAP-first
`sys.settrace`-based debuggers have notorious overhead. `sys.monitoring` provides **VM-level event monitoring** intended for debuggers, coverage, profilers, and optimizers.

Notable properties (from docs):
- A small number of **tool IDs** (0–5), with conventional IDs like `DEBUGGER_ID = 0`.
- Monitoring can be enabled at different granularities; includes events like `LINE`, `CALL`, `PY_START`, etc.
- Includes **branch events** (`BRANCH_LEFT`, `BRANCH_RIGHT`) and control-flow events (`JUMP`), enabling richer “execution path” UIs.

Implication: even if yathaavat’s initial backend is `debugpy`, the long-term “best-in-class performance” path is likely a **native 3.14+ backend** that leverages `sys.monitoring` for break/step with reduced overhead.

Source:
- `sys.monitoring` docs: https://docs.python.org/3.14/library/sys.monitoring.html

---

## 4) Free-threaded CPython (PEP 703) and attach compatibility

Python 3.14 improves free-threaded mode significantly (initially added in 3.13).

Two debugger-relevant implications:
1. **Concurrency UX is no longer optional**: thread/task views must be first-class and fast.
2. PEP 768 protocol validation includes a **`free_threaded` compatibility check** when attaching (the HOWTO’s `_Py_DebugOffsets` validation includes checking `free_threaded`).

Sources:
- What’s New (free-threaded mode improvements): https://docs.python.org/3.14/whatsnew/3.14.html
- Remote debugging protocol validation notes: https://docs.python.org/3.14/howto/remote_debugging.html

---

## 5) Typing + annotation semantics (PEP 649) and debugger UI

Python 3.14 implements **PEP 649**, changing how annotations are computed:
- Annotations are computed lazily via `__annotate__` and cached when accessed via `__annotations__`.
- `inspect.get_annotations()` and `typing.get_type_hints()` gain a `format` parameter for controlling evaluation and forward refs.

Debugger implication:
- “Type-aware inspection” should prefer **non-invasive** introspection paths. Eagerly forcing annotation evaluation can be slow, can trigger imports, or can produce confusing errors in partially-initialized modules.

Additional runtime typing changes in 3.14:
- `types.UnionType` and `typing.Union` become aliases for each other; `repr(Union[int, str])` matches `int | str`.

Sources:
- PEP 649 (historical): https://peps.python.org/pep-0649/
- What’s New (typing changes): https://docs.python.org/3.14/whatsnew/3.14.html

---

## Concrete takeaways for yathaavat v2

1. **Make safe attach a handshake protocol**: since `sys.remote_exec()` has no completion signal, yathaavat must define a “ready” signal (file, socket, or reverse-connect) with timeouts and clear UX.
2. **Treat permission failures as normal**: guide users through ptrace/admin restrictions with actionable remediation in-app.
3. **Plan a native backend track**: `sys.monitoring` is the most credible path to “debugger that doesn’t melt prod”.
4. **Make async/thread visualization core**: free-threaded and modern async workloads make this non-negotiable.
5. **Be cautious with type hints**: show runtime type first; treat annotations as optional “on-demand” enrichment.

