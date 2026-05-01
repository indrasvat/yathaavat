---
name: kasm-drive
description: Run and verify yathaavat interactively in a Linux Kasm desktop. Use when the user asks to build, install, launch, drive, screenshot, or smoke-test yathaavat demos through the Kasm/X11 desktop container, especially with debugpy demos, terminal TUI flows, xdotool input, or ffmpeg screenshots. This skill is Linux-only and is not suitable for macOS/iTerm automation.
---

# Kasm Drive

Use this skill to launch `yathaavat` inside the Linux Kasm desktop, drive it with real desktop input, and capture screenshots for review. Do not use this for macOS; use the existing iTerm automation path there.

## Preconditions

- Run on a Linux host with Docker access.
- Expect the Kasm desktop container to be named `desk`.
- Prefer `konsole` if present in the container; otherwise use `xfce4-terminal`, then `xterm`.
- Expect the Kasm display to be `:1` with `/home/kasm-user/.Xauthority`.
- If Codex exposes desktop MCP tools, use them. If not, use the same bridge directly with `docker exec desk xdotool` and `ffmpeg`.

## Quick Check

```bash
docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}'
docker exec desk bash -lc 'echo DISPLAY=$DISPLAY; command -v konsole || command -v xfce4-terminal || command -v xterm; command -v xdotool; command -v xdpyinfo; command -v ffmpeg'
docker exec desk bash -lc 'xdpyinfo | sed -n "1,20p"'
```

If `desk`, `xdotool`, `xdpyinfo`, or `ffmpeg` is missing, stop and report the missing desktop bridge.

## Host Build

From the yathaavat checkout:

```bash
uv sync --python python3.14 --all-extras
uv run --python python3.14 pytest -q
uv tool install --force --python python3.14 .
yathaavat --version
```

If `pytest` is missing, run `uv sync --python python3.14 --all-extras` first. If `uv` must provision Python 3.14, allow it to download the managed interpreter.

## Prepare Kasm

Copy the current source tree and `uv` into the Kasm container:

```bash
docker exec desk bash -lc 'rm -rf /home/kasm-user/yathaavat-demo && mkdir -p /home/kasm-user/yathaavat-demo'
tar --exclude='.git' --exclude='.venv' --exclude='.mypy_cache' --exclude='.pytest_cache' --exclude='.ruff_cache' \
  -cf - . | docker exec -i desk tar -xf - -C /home/kasm-user/yathaavat-demo
docker exec desk chown -R kasm-user:kasm-user /home/kasm-user/yathaavat-demo

docker cp "$(command -v uv)" desk:/usr/local/bin/uv
docker exec desk chmod +x /usr/local/bin/uv
```

If the Kasm container cannot download from GitHub or PyPI, reuse the host's `uv` Python and cache:

```bash
PYDIR=$(find "$(uv python dir)" -maxdepth 1 -type d -name 'cpython-3.14*' | sort -V | tail -1)
tar -C "$(dirname "$PYDIR")" -cf - "$(basename "$PYDIR")" \
  | docker exec -i desk tar -xf - -C /home/kasm-user/.local/share/uv/python
tar -C "$HOME/.cache" -cf - uv \
  | docker exec -i desk tar -xf - -C /home/kasm-user/.cache
docker exec desk chown -R kasm-user:kasm-user /home/kasm-user/.local/share/uv/python /home/kasm-user/.cache/uv
```

Because `.git` is intentionally not copied, set a pretend version for Hatch/VCS builds:

```bash
docker exec desk bash -lc '
cd /home/kasm-user/yathaavat-demo &&
SETUPTOOLS_SCM_PRETEND_VERSION=0.4.1.dev1 \
/usr/local/bin/uv run --offline --python python3.14 yathaavat --version
'
```

Use online `uv run` instead of `--offline` only when the container has reliable outbound access.

## Launch The TUI

Pick the terminal available in the container:

```bash
TERM_CMD=$(docker exec desk bash -lc 'command -v konsole || command -v xfce4-terminal || command -v xterm')
```

For the common `xfce4-terminal` case:

```bash
docker exec -u kasm-user -d desk bash -lc '
cd /home/kasm-user/yathaavat-demo &&
DISPLAY=:1 XAUTHORITY=/home/kasm-user/.Xauthority \
xfce4-terminal --geometry=140x42 --title=yathaavat-demo \
--command "bash -lc '\''cd /home/kasm-user/yathaavat-demo; export SETUPTOOLS_SCM_PRETEND_VERSION=0.4.1.dev1; /usr/local/bin/uv run --offline --python python3.14 yathaavat; exec bash'\''"
'
```

If using `konsole`, adapt the command shape:

```bash
docker exec -u kasm-user -d desk bash -lc '
cd /home/kasm-user/yathaavat-demo &&
DISPLAY=:1 XAUTHORITY=/home/kasm-user/.Xauthority \
konsole --workdir /home/kasm-user/yathaavat-demo \
--title yathaavat-demo \
-e bash -lc "export SETUPTOOLS_SCM_PRETEND_VERSION=0.4.1.dev1; /usr/local/bin/uv run --offline --python python3.14 yathaavat; exec bash"
'
```

Wait for the terminal and focus it:

```bash
sleep 3
docker exec desk bash -lc 'xdotool search --name yathaavat-demo windowactivate; xdotool getwindowfocus getwindowname'
```

## Drive A Demo

Launch `examples/demo_target.py` through the TUI:

```bash
docker exec desk bash -lc '
xdotool search --name yathaavat-demo windowactivate
sleep 0.2
xdotool key ctrl+r
sleep 0.5
xdotool type --delay 30 -- examples/demo_target.py
sleep 0.2
xdotool key Return
'
```

Expected result: the status shows `PAUSED`, backend `debugpy`, source around `demo_target.py:31`, and the transcript includes launch/connect/stop messages.

To inspect locals, click or key to the Locals tab. If coordinates are used, capture a screenshot first and choose positions from the 1024x768 frame.

## Capture Screenshots

Always write screenshots to a host-visible directory:

```bash
mkdir -p /home/ubuntu/workspace/yathaavat-kasm
docker exec desk bash -lc '
WH=$(xdpyinfo | awk "/dimensions:/ {print \$2; exit}")
ffmpeg -y -loglevel error -f x11grab -video_size "$WH" -i "$DISPLAY" -frames 1 /tmp/yathaavat.png
'
docker cp desk:/tmp/yathaavat.png /home/ubuntu/workspace/yathaavat-kasm/screenshot.png
ls -lh /home/ubuntu/workspace/yathaavat-kasm/screenshot.png
```

For remote user viewing, local paths may not render in chat. Prefer an approved artifact path, such as a temporary private GitHub branch, and delete it after confirmation. Do not expose Kasm auth tokens.

## Cleanup

Close only windows/processes created for this run:

```bash
docker exec desk bash -lc 'xdotool search --name yathaavat-demo windowclose || true'
```

Remove temporary remote artifact branches after the user confirms they saw the screenshots.
