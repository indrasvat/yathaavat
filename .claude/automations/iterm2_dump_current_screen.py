# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "iterm2",
#   "pyobjc",
# ]
# ///

from __future__ import annotations

import iterm2


async def main(connection: iterm2.Connection) -> None:
    app = await iterm2.async_get_app(connection)
    window = app.current_terminal_window
    if window is None or window.current_tab is None or window.current_tab.current_session is None:
        raise RuntimeError("No active iTerm2 session found")

    session = window.current_tab.current_session
    screen = await session.async_get_screen_contents()
    lines = [screen.line(i).string for i in range(screen.number_of_lines)]
    text = "\n".join(lines)
    print(text)


if __name__ == "__main__":
    iterm2.run_until_complete(main)
