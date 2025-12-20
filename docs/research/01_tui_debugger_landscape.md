# TUI Debugger Landscape (Python) — What Works / What Doesn’t

Last updated: 2025-12-20

This is a focused survey of Python’s “terminal debugging” ecosystem and adjacent inspirations (DAP backends, REPLs, and classic TUIs). The goal is to extract *specific, proven UX patterns* for yathaavat v2.

---

## 1) Built-in `pdb` (Python 3.14+)

### Notable 3.14 changes that matter for yathaavat
- **Remote attach by PID**: `python -m pdb -p 1234` (built on PEP 768 + `sys.remote_exec()`).
- **Async-friendly affordances** (from the 3.14 changelog): `pdb.set_trace_async()` and `$_asynctask` convenience handle.
- **Better input UX**: multi-line auto-indent; syntax-highlighted source listings.

### What works (steal these ideas)
- **Predictable mental model**: “prompt + commands”, with minimal UI abstraction.
- **Safety**: remote attach is *runtime-supported* and designed with security knobs.

### What doesn’t (for yathaavat’s goals)
- **Low information density**: prompt-driven flows mean lots of context switching vs. an always-visible “source + stack + variables” view.
- **Discoverability ceiling**: command lists are learnable, but require memorization compared to palette + contextual menus.

Sources:
- Python 3.14 `pdb -p/--pid` docs: https://docs.python.org/3.14/library/pdb.html
- Python 3.14 “What’s New” (`pdb`, PEP 768): https://docs.python.org/3.14/whatsnew/3.14.html

---

## 2) `pdb++` (`pdbpp`) — the “power prompt”

### What it is
Drop-in replacement for `pdb` with quality-of-life features: **sticky mode**, richer completion, syntax highlighting, smart parsing, and extra commands.

### What works (high-signal patterns)
- **Sticky mode**: repaint + show the whole function when stepping. This reduces “where am I?” thrash.
- **“Display list” watches**: expressions that are automatically re-evaluated and only printed on change.
- **Smart command parsing**: resolving ambiguities by preferring in-scope variables (and forcing commands via prefix).

### What doesn’t
- **Still prompt-first**: great for experts, but not “zero friction” for newcomers.
- **Side-effect footguns**: display/watch expressions being re-evaluated repeatedly is inherently risky.

Sources:
- `pdbpp` README: https://raw.githubusercontent.com/pdbpp/pdbpp/master/README.rst

---

## 3) PuDB — “IDE-like debugging inside a terminal”

### What it is
A full-screen console debugger (urwid-based) that keeps source/stack/breakpoints/variables visible together.

### What works (directly relevant)
- **Always-visible triad**: source + stack + vars is the right default for “visual debugging”.
- **Single-keystroke workflows**: navigation and breakpoints with minimal chords.
- **Post-mortem emphasis**: crash workflows are first-class.
- **Secondary power tools**: module browser; drop to shell; separate-terminal control.

### What doesn’t / common friction
- **UI framework limits**: curses/urwid UIs can be brittle around resizing, mouse, unicode width, truecolor, and high-frequency updates.
- **Scaling pain**: large data structures and huge stacks tend to overwhelm “tree expansion” UIs without strong virtualization/paging.

Sources:
- PuDB README: https://raw.githubusercontent.com/inducer/pudb/main/README.rst
- PuDB dependencies (urwid/jedi/pygments): https://raw.githubusercontent.com/inducer/pudb/main/pyproject.toml

---

## 4) `debugpy` — DAP backend (and why it’s still the default)

### What it is
Python Debug Adapter Protocol implementation; widely supported by editors and tooling.

### What works for yathaavat
- **DAP compatibility**: stable protocol surface, mature clients/servers, future backend swap potential.
- **Convenient workflows**: `--listen`, `--wait-for-client`, and attach-by-PID injection flows are familiar to developers.
- **Security messaging**: explicit warning that exposing the debug port allows arbitrary code execution.

### What doesn’t / risks
- **Attach-by-PID historically relied on unsafe injection techniques** (platform debuggers); Python 3.14’s safe attach can replace this path for CPython 3.14+ targets.
- **Feature mismatch**: DAP is generic; Python-specific UX (async task trees, exception groups) often needs extra work or custom requests.

Sources:
- debugpy README: https://raw.githubusercontent.com/microsoft/debugpy/main/README.md

---

## 5) REPLs (`bpython`, IPython, ptpython) — “make evaluation delightful”

### Why this matters
A debugger lives or dies by its **evaluation experience** (history, multiline editing, completions, safe pretty-printing).

### What bpython demonstrates well
- **Inline help while typing** (expected parameter list).
- **High-quality interactive editing** (auto-indent, rewind, edit session).
- **Autocomplete + highlighting** that feels IDE-like without being heavy.

Sources:
- bpython README: https://raw.githubusercontent.com/bpython/bpython/master/README.rst

---

## 6) Adjacent inspirations (non-Python)

Even if not Python-specific, these tools teach proven TUI interaction patterns:

- **gdb TUI / lldb**: stable layouts, “source + asm + regs”, explicit “layout” commands, predictable keybindings.
- **lazygit / k9s / tig / yazi**: bottom help bar, command palette/search-first workflows, fast filtering, “minimal chrome”.

---

## Takeaways for yathaavat v2 (actionable)

1. **Default to an always-visible “source + stack + variables” screen** (PuDB’s core value), but with modern virtualization and resizing.
2. **Adopt sticky-mode semantics** (pdb++): stepping should keep relevant context anchored without manual scrolling.
3. **Make watches safe-by-default**: preview/poll only when paused; clearly label side-effect risk for “live watches”.
4. **Treat evaluation as a product**: multiline editing, history, completions, copy/paste ergonomics; optionally “REPL-like” without embedding a full REPL.
5. **Use Python 3.14 safe attach as the canonical production attach** path for CPython 3.14+.

