---
name: kurukshetra-debug-gauntlet
description: "Run a realistic yathaavat debugger dogfood gauntlet with subagents: generate an isolated buggy Python/uv target app, have a separate persona debug it through the yathaavat TUI driven by shux, capture UX/DX friction, verify findings, and implement product fixes. Use for yathaavat release gates, debugger UX validation, shux-backed TUI dogfooding, or requests to create scenario-based debugging evaluations."
---

# Kurukshetra Debug Gauntlet

Use this skill to test yathaavat against a fresh, realistic debugging scenario rather than a hand-written happy path.

## Preflight

From repo root:

```bash
python .claude/skills/kurukshetra-debug-gauntlet/scripts/preflight.py
```

Fix failed checks before spawning agents. Default all generated targets, logs, screenshots, and evidence to `/tmp/yathaavat-gauntlet/<slug>/`. Use repo-local ignored dirs only when the user explicitly asks for a persistent artifact.

## Agent Names

Assign spawned agents names from Sanskrit literature. Use a fresh name per role in prompts and report headings:

`Viśvakarman`, `Nārada`, `Gārgī`, `Maitreyi`, `Vyāsa`, `Vālmīki`, `Sītā`, `Draupadī`, `Arjuna`, `Abhimanyu`, `Vidura`, `Savitri`, `Śakuntalā`, `Lopāmudrā`, `Agastya`, `Bharadvāja`.

If the tool auto-generates nicknames, still use the chosen name inside the prompt and final report.

## Workflow

1. **Create the target app** with an expert Python subagent.
   - Write only under `/tmp/yathaavat-gauntlet/<slug>/target/`.
   - Use Python 3.14+ and `uv`.
   - Build a non-trivial runnable service/script with realistic state, concurrency, cache, IO, or protocol behavior.
   - Include deliberate subtle bugs, but do not label root causes.
   - Include `README.md`, `ISSUE.md`, `pyproject.toml`, lockfile, and a deterministic repro command.
   - Require the subagent to verify `uv sync`, compile/help, and repro.

2. **Run the debugger pass** with a different beginner/intermediate or role-specific subagent.
   - Give only `README.md`, `ISSUE.md`, repo path, and tool constraints.
   - Require yathaavat TUI use through shux; source reading is allowed only as normal debugging context.
   - Prefer `Ctrl+R` launch with a real absolute `uv --directory /tmp/yathaavat-gauntlet/<slug>/target run ...` command after `uv sync`.
   - Use `Ctrl+K` connect only when launch is not the workflow under test.
   - Require at least one conditional breakpoint, one locals/scope inspection, and one screenshot or pane capture.
   - Ask: could the issue be debugged mostly in the TUI, what broke, what was awkward, and what is app bug vs yathaavat bug?

3. **Verify findings locally** before editing.
   - Reproduce the app issue yourself.
   - Reproduce each reported yathaavat friction with the smallest shux/TUI path.
   - Discard vague complaints unless they have a concrete reproduction or screenshot.

4. **Fix yathaavat only after verification.**
   - Create or switch to a focused branch first.
   - Keep `/tmp/yathaavat-gauntlet/<slug>/target/` bugs intact unless the user explicitly asks to repair the target app.
   - Add regression tests for product fixes.
   - Run focused tests, then `make ci`.

5. **Run a validation pass** with a new persona after fixes.
   - Use the same scenario when validating setup/friction fixes.
   - Use a different scenario only when the original scenario no longer exercises the feature.
   - Patch remaining concrete regressions, then rerun CI.

## Shux Patterns

Use unique session names:

```bash
shux session create yv-<slug> -d --title yathaavat -- \
  env -u NO_COLOR TERM=xterm-256color COLORTERM=truecolor FORCE_COLOR=1 \
  uv run --python python3.14 yathaavat tui
shux pane set-size -s yv-<slug> --cols 150 --rows 45
shux pane wait-for -s yv-<slug> --text yathaavat --timeout-ms 10000
```

Capture evidence outside the repo:

```bash
mkdir -p /tmp/yathaavat-gauntlet/<slug>/evidence
shux --format json pane snapshot -s yv-<slug> \
  | jq -r .png_base64 | base64 -d > /tmp/yathaavat-gauntlet/<slug>/evidence/screen.png
shux pane capture -s yv-<slug> > /tmp/yathaavat-gauntlet/<slug>/evidence/screen.txt
```

Cleanup:

```bash
session="yv-<slug>"
cleanup() {
  shux session kill "$session" >/dev/null 2>&1 || true
  lsof -ti tcp:<port> | xargs -r kill >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM
```

## Friction Guardrails

Explicitly test the known sharp edges:

- `Ctrl+R` with `uv --directory /tmp/yathaavat-gauntlet/<slug>/target run <entrypoint> ...`.
- Visible picker row + Enter selection.
- Natural breakpoint condition: `path:line if tenant == "greenfield"`.
- `Esc` from expression/watch modals.
- Function-key debug controls, especially `F5`; do not rely only on single-letter keys inside text inputs.
- Time-sensitive bugs where pausing may alter cache TTLs, locks, or races.

## Report Shape

Keep the final report terse:

- scenario path and repro command
- agents used and roles
- yathaavat issues found/fixed
- evidence paths
- branch name
- verification command results
- remaining follow-up candidates
