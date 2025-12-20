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
    for idx, window in enumerate(windows):
        print(f"\nWindow[{idx}] type={type(window)!r}")
        attrs = [a for a in dir(window) if not a.startswith("_")]
        for name in [
            "window_id",
            "tabs",
            "current_tab",
            "current_session",
            "frame",
            "name",
            "number",
        ]:
            if name in attrs:
                try:
                    value = getattr(window, name)
                except Exception as exc:
                    value = f"<error {exc!r}>"
                print(f"  {name}: {value!r}")
        print(f"  attr sample: {attrs[:18]}")


if __name__ == "__main__":
    iterm2.run_until_complete(main)
