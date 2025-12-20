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
    windows = app.terminal_windows
    print(f"windows: {len(windows)}")
    for w_idx, window in enumerate(windows):
        print(f"\nWindow[{w_idx}] id={window.window_id}")
        for t_idx, tab in enumerate(window.tabs):
            print(f"  Tab[{t_idx}] id={tab.tab_id}")
            for s_idx, session in enumerate(tab.sessions):
                print(f"    Session[{s_idx}] id={session.session_id} name={session.name!r}")


if __name__ == "__main__":
    iterm2.run_until_complete(main)
