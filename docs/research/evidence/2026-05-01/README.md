# Kasm TUI Evidence (May 1, 2026)

Screenshots captured from the configured Linux KasmVNC desktop.

- `attach-picker-safe-probe.png`: the attach picker filtered to two generic `python` CPython 3.14 targets. The normal target is shown as `py3.14 safe`; the target launched with `PYTHON_DISABLE_REMOTE_DEBUG=1` is shown as `py3.14 safe off`.
- `safe-attach-route-attempt.png`: pressing Enter on a `py3.14 safe` target routes to the existing `sys.remote_exec` safe attach flow. The Kasm/uv CPython runtime then reports `PyRuntime address lookup failed during debug offsets initialization`; yathaavat now explains this as a likely Linux ptrace/container capability failure and shows `CAP_SYS_PTRACE`, unconfined seccomp, and `kernel.yama.ptrace_scope` remediation guidance.
- `attach-existing-dap.png`: the attach picker detects a running `python -m debugpy --listen 127.0.0.1:5678` target and labels it as `py3.14 dap 127.0.0.1:5678`, proving the picker prefers connecting to an existing DAP endpoint instead of reinjecting.
- `attach-x-disable-safe-off.png`: the attach picker detects a target launched with `-X disable_remote_debug` and labels it as `py3.14 safe off`.
- `launch-demo-paused.png`: a control scenario showing the updated build can launch `examples/demo_target.py` under debugpy and pause in the TUI at `demo_target.py:31`.
