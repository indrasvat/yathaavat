# Kasm TUI Evidence (May 1, 2026)

Screenshots captured from the configured Linux KasmVNC desktop.

- `attach-picker-safe-probe.png`: the attach picker filtered to two generic `python` CPython 3.14 targets. The normal target is shown as `py3.14 safe`; the target launched with `PYTHON_DISABLE_REMOTE_DEBUG=1` is shown as `py3.14 safe off`.
- `safe-attach-route-attempt.png`: pressing Enter on a `py3.14 safe` target routes to the existing `sys.remote_exec` safe attach flow. The Kasm/uv CPython runtime then reports `PyRuntime address lookup failed during debug offsets initialization`; yathaavat now explains this as a likely Linux ptrace/container capability failure and shows `CAP_SYS_PTRACE`, unconfined seccomp, and `kernel.yama.ptrace_scope` remediation guidance.
