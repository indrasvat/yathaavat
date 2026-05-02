# Python 3.14 Debugger Gap Analysis (May 1, 2026)

This note compares current Python 3.14 debugger capabilities against yathaavat and records the focused feature added in this change.

## Python 3.14 debugger features researched

- **PEP 768 safe external debugger interface**: CPython 3.14 exposes a safe-point based attach mechanism and `sys.remote_exec(pid, script)`, allowing a debugger to schedule a Python file in a running CPython process without unsafe arbitrary interpreter interruption.
- **`pdb -p PID`**: stdlib `pdb` can attach to a running process by PID using the PEP 768 mechanism.
- **Remote attach constraints**: attach may wait until the target reaches the next bytecode/safe point; local and target CPython major/minor versions must match; admins can disable it with `PYTHON_DISABLE_REMOTE_DEBUG`, `-X disable_remote_debug`, or `--without-remote-debug`; OS permissions still apply.
- **Async pdb improvements**: `pdb.set_trace_async()` supports await-aware debugging and 3.14 adds the `$_asynctask` convenience variable.
- **pdb backend/color controls**: `pdb.Pdb` gained `mode`, `backend`, and `colorize`; `set_default_backend()` can choose between `settrace` and `monitoring`.
- **debugpy ecosystem state**: debugpy publishes CPython 3.14 wheels, so a DAP client can keep using debugpy as its adapter layer for 3.14 targets.

Sources:
- https://docs.python.org/3/whatsnew/3.14.html
- https://docs.python.org/3/library/pdb.html
- https://docs.python.org/3/library/sys.html#sys.remote_exec
- https://docs.python.org/3/howto/remote_debugging.html
- https://docs.python.org/3/using/cmdline.html#envvar-PYTHON_DISABLE_REMOTE_DEBUG
- https://peps.python.org/pep-0768/
- https://pypi.org/project/debugpy/

## yathaavat today

yathaavat already has material coverage:

- Launch/connect/attach workflows over DAP/debugpy.
- PEP 768 safe attach via `sys.remote_exec()`, with a temp-file handoff and status-file handshake.
- PID attach fallback through `debugpy --pid`.
- Attach picker that detects existing debugpy DAP endpoints and can route to connect instead of reinjecting.
- Breakpoints, run-to-cursor, source find/goto, locals, watches, expression console with completions, exception tree, and asyncio task panels.

## Gaps

- **Safe attach candidate detection was too brittle**: the picker only marked a process as safe-attach capable when the process command advertised `python3.14` or `python@3.14`. Common production forms such as `python -m service`, venv `python`, or process-manager launched interpreters could be real CPython 3.14 targets but were treated as legacy attach candidates.
- **Remote-debug policy was invisible**: if the target was launched with `PYTHON_DISABLE_REMOTE_DEBUG` or `-X disable_remote_debug`, the picker could still advertise safe attach.
- **No native pdb parity** for `pdb.set_trace_async()`, `$_asynctask`, pdb aliases, or pdb `display` commands. yathaavat covers many of these through DAP concepts, but not as pdb-compatible commands.
- **No native `sys.monitoring` backend**. yathaavat currently relies on debugpy/DAP, which is pragmatic but not the lowest-overhead long-term backend.
- **No subprocess/process-tree debugging UI** despite debugpy support for related workflows.

## Focused feature selected

Add a **Python 3.14 safe-attach capability probe** to process discovery.

Plan:

1. For Python-looking processes without a version hint, probe `/proc/<pid>/exe` by running the same interpreter in isolated no-site mode and reading `sys.version_info.major/minor`.
2. Read target launch policy from `/proc/<pid>/environ` and command-line `-X` flags to detect disabled remote debugging.
3. Surface that capability in the existing attach picker:
   - `py3.14 safe` for viable PEP 768 candidates,
   - `py3.14 safe off` when remote debugging is disabled or local privileges are insufficient.
4. Keep behavior conservative: if probes fail, leave existing fallback behavior untouched.
5. Verify with unit tests and an interactive KasmVNC TUI run.

Kasm evidence:

- `docs/research/evidence/2026-05-01/attach-picker-safe-probe.png`
- `docs/research/evidence/2026-05-01/safe-attach-route-attempt.png`
- `docs/research/evidence/2026-05-01/attach-existing-dap.png`
- `docs/research/evidence/2026-05-01/attach-x-disable-safe-off.png`
- `docs/research/evidence/2026-05-01/launch-demo-paused.png`

Why this feature:

- It directly improves the most important Python 3.14 debugger capability yathaavat already owns: safe attach.
- It is small and low risk because it reuses the existing safe attach path rather than changing DAP/session internals.
- It prevents a real production UX failure where `python`-named 3.14 services are incorrectly routed to legacy attach.
