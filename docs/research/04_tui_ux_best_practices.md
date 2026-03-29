# UI/UX Best Practices for TUIs (Debugger-Focused)

Last updated: 2025-12-20

This note distills best practices for designing high-performance, keyboard-driven TUIs with high information density and strong discoverability—specifically in the debugger domain.

---

## 1) The core tradeoff: density vs. clarity

Debugger TUIs must show a lot:
- source context,
- execution context (thread/frame),
- data context (locals/watches),
- output context (console/log),
…without becoming a wall of noise.

Practical guidance:
- Prefer **structured density** (aligned columns, consistent indentation, tight typography) over whitespace.
- Use **progressive disclosure**: always show previews; expand on demand; never auto-expand large objects.
- Maintain a stable “**anchor**”: the current frame + current source location should remain visually stable while stepping.

---

## 2) Keyboard ergonomics: optimize for stepping loops

Debugging is often a tight loop of:
`step → glance → eval → step → adjust breakpoint → continue`.

Guidance:
- Put the stepping cluster on **single keys** and/or standard function keys; allow users to choose.
- Avoid requiring modifiers for the common loop (reserve chords for navigation/search/global actions).
- Provide “sticky context” (pdb++ calls this sticky mode): stepping should keep relevant source context visible without manual scrolling.

Source inspiration:
- `pdb++` sticky mode: https://raw.githubusercontent.com/pdbpp/pdbpp/master/README.rst

---

## 3) Discoverability: “teach as you go”

TUIs typically fail users when:
- shortcuts are hidden,
- actions are contextual but undiscoverable,
- the app has multiple “modes” without visible state.

Patterns that work:
- **Command palette** as the top-level entrypoint (fuzzy search actions + show keybindings).
- A one-key **help overlay** (`?`) that is contextual to the focused pane.
- A **bottom help bar** with the 4–8 most relevant actions for the current state (paused vs running).
- “Empty state” prompts that teach the next best action (e.g., no breakpoints → show “press `b` to add”).

---

## 4) Focus, selection, and “what will Enter do?”

In debugger TUIs, ambiguity kills confidence. Make these explicit:
- **Focus** (where keys go),
- **Selection** (what is highlighted),
- **Primary action** (what Enter triggers).

Guidelines:
- Use strong focus cues (reverse video / underline / caret marker), not just subtle borders.
- Keep `Enter` consistent: “open/expand/jump” within the focused pane.
- Keep `Esc` consistent: “cancel/close/back”, never “quit”.

---

## 5) Search and filtering must be instant

Debuggers have lots of lists: files, frames, breakpoints, vars, tasks, logs.

Guidelines:
- Make `/` a fast “filter within current list” with incremental results.
- Use the palette for “global” search (files/symbols/commands).
- Preserve selection while filtering; allow “clear filter” with a single key.

Performance rule of thumb:
- Search results should update within a single frame budget (tens of ms), otherwise the user experiences “lag”.

---

## 6) Error design and recovery

In real debugging, things fail:
- target exits,
- adapter disconnects,
- breakpoints can’t bind,
- evaluation errors,
- attach permission denied.

Guidelines:
- Always show the **state** (connected/disconnected/running/paused) in a stable place.
- Errors should be **actionable** (“Run with sudo”, “Set ptrace_scope”, “Enable remote debug”), not just stack traces.
- Prefer non-blocking notifications; reserve blocking dialogs for dangerous actions (stop process, bind public port).

---

## 7) Terminal constraints: design for the smallest usable screen

If the UI only works on a large terminal, it will fail in:
- SSH sessions,
- split panes,
- laptops,
- tmux/screen.

Guidelines:
- Define explicit breakpoints for layouts (e.g., 80×24 “compact”, 120×34 “standard”, 160×45 “wide”).
- Provide a single-key layout switcher (cycle layouts).
- Offer an `--ascii` mode for hostile fonts/Unicode-width environments.

---

## 8) “Developer delight” details that matter

Small wins that compound:
- Copy value / copy path / copy stacktrace as one-keystroke actions.
- “Recent commands” and “repeat last eval”.
- Smart truncation with “expand” (show bytes/len/type always).
- A transcript that is shareable and replayable (incident-friendly).

