# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "iterm2",
#   "pyobjc",
# ]
# ///

from __future__ import annotations

import asyncio

import iterm2


async def _screen_text(session: iterm2.Session) -> str:
    screen = await session.async_get_screen_contents()
    lines = [screen.line(i).string for i in range(screen.number_of_lines)]
    return "\n".join(lines)


async def main(connection: iterm2.Connection) -> None:
    app = await iterm2.async_get_app(connection)
    window = app.current_terminal_window
    if window is None:
        raise RuntimeError("No active iTerm2 window found")

    needles = ["__YATHAAVAT_MARKER__", "yathaavat", "Launch under debugpy", "DISCONNECTED"]
    print(f"Searching {len(window.tabs)} tabs for: {needles!r}")

    matches: list[tuple[int, str, str]] = []

    for tab in window.tabs:
        for session in tab.sessions:
            try:
                text = await asyncio.wait_for(_screen_text(session), timeout=1.5)
            except TimeoutError:
                continue
            if any(n in text for n in needles):
                matches.append((tab.tab_id, session.session_id, session.name))
                print(f"match tab={tab.tab_id} session={session.session_id} name={session.name!r}")

    if not matches:
        print("No matches.")


if __name__ == "__main__":
    iterm2.run_until_complete(main)
