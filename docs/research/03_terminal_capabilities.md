# Terminal Capabilities & Constraints (Warp / Ghostty / iTerm2 / Kitty)

Last updated: 2025-12-20

This note summarizes terminal capabilities that matter for a *production-ready* TUI debugger: keyboard fidelity, mouse support, color, Unicode rendering, and performance characteristics.

---

## 1) The practical baseline (what we can assume)

For “modern developer terminals” in 2025, it’s reasonable to assume:
- **Alternate screen** support (full-screen TUIs).
- **256 colors** at minimum; **truecolor (24-bit)** in most cases.
- **Bracketed paste** (so pasted code doesn’t trigger keybindings).
- **SGR mouse reporting** (many terminals), but must be opt-in and degrade gracefully.
- **Unicode** rendering with box drawing (with occasional width quirks).

What we cannot assume:
- pixel-perfect fonts or consistent glyph widths (emoji/CJK/ligatures vary),
- reliable differentiation of all modifier combos without an extended keyboard protocol,
- high performance for pathological redraw patterns (e.g., repainting the whole screen on every log line).

---

## 2) Keyboard fidelity: why kitty keyboard protocol matters

Classic terminal key handling has hard limits:
- ambiguous escape sequences,
- limited modifier reporting beyond ctrl/alt,
- brittle timing hacks to disambiguate `Esc` vs escape sequence prefixes.

kitty’s keyboard protocol exists specifically to address these issues and is implemented in multiple modern terminals and libraries, including Textual:
- terminals: kitty, Ghostty, iTerm2 (per kitty’s tracking), Alacritty, WezTerm, foot, etc.
- libraries: Textual, bubbletea, crossterm, notcurses, etc.

**Design implication for yathaavat**: enable kitty keyboard protocol when available to support a richer, conflict-free keymap (especially for chords like `Ctrl+Shift+…`, distinguishing `Esc` behavior, and robust shortcuts across keyboard layouts).

Source:
- kitty keyboard protocol overview + adoption list: https://sw.kovidgoyal.net/kitty/keyboard-protocol/

---

## 3) Per-terminal notes

### Kitty
- Reference implementation for several “modern terminal” protocols (keyboard, graphics, remote control).
- Typically high performance and consistent behavior for TUIs that do frequent partial updates.

### Ghostty
- Explicit focus on *standards compliance* and *performance*; targets ~60fps under heavy load and has a dedicated IO thread to reduce jitter.
- Notes that it provides a Metal renderer on macOS (and mentions iTerm ligature performance tradeoffs).

Design implication: Ghostty is a strong “stress test” terminal for responsiveness; if yathaavat feels instant in Ghostty, it’s likely fine elsewhere.

Source:
- Ghostty README (performance + renderer notes): https://raw.githubusercontent.com/ghostty-org/ghostty/main/README.md

### iTerm2
- Widely used on macOS; supports many xterm conventions.
- kitty keyboard protocol is tracked as implemented (per kitty’s adoption list), but robust behavior should still be feature-detected, not assumed.

### Warp
- “Modern terminal + shell experience” with a UI layer that differs from classic terminals in some behaviors.
- Treat as “mostly xterm-like”, but design yathaavat to survive partial protocol support (especially around mouse and exotic key chords).

Note: Warp’s public docs are heavily dynamic, so this note avoids making brittle, source-uncited claims beyond the general constraint: *feature-detect and degrade*.

---

## 4) Mouse support (optional, never required)

Best practice for debuggers: keyboard-first, mouse-enabled for convenience.

Guidelines:
- Mouse should enhance core flows (select variable, scroll, set breakpoint), not be required.
- Provide an explicit “mouse on/off” toggle in Settings and a runtime auto-detect.
- Ensure SHIFT+mouse passthrough where possible (common TUI convention).

---

## 5) Truecolor, theming, and accessibility

Guidelines:
- Treat truecolor as an optimization; maintain a 256-color fallback palette.
- Avoid relying on low-contrast “subtle borders” that disappear in some themes.
- Use minimal but strong focus cues: reverse video, underline, or a clear caret marker.

---

## 6) Unicode, glyph width, and “terminal typography”

Constraints:
- Emoji and some symbols have inconsistent width across terminals and fonts.
- Ligatures can change perceived spacing; some terminals implement ligatures with performance tradeoffs.

Guidelines:
- Prefer ASCII + box drawing for core chrome; avoid emoji in structural UI.
- Use a width library (wcwidth) and test with mixed-width content.
- Provide `--ascii` mode that replaces box drawing with `+|-` and removes ambiguous glyphs.

---

## 7) Performance constraints (what will make TUIs feel “laggy”)

Primary causes of perceived lag in terminals:
- repainting the entire screen too frequently,
- large diff regions when only a small portion changed,
- rendering huge text blobs (logs, pretty-printed objects) without virtualization.

Guidelines for yathaavat:
- Prefer incremental updates and viewport virtualization for large lists/logs.
- Debounce “high-churn” panels (stdout/transcript) while the user is typing.
- Keep the “keystroke → paint” path under tight latency budgets (see v2 design doc).

