from __future__ import annotations


def format_key(key: str) -> str:
    parts = [p.strip() for p in key.split("+") if p.strip()]
    if not parts:
        return key

    out: list[str] = []
    for part in parts:
        lower = part.lower()
        match lower:
            case "ctrl" | "control":
                out.append("Ctrl")
            case "alt" | "option":
                out.append("Alt")
            case "shift":
                out.append("Shift")
            case "meta" | "cmd" | "command":
                out.append("Meta")
            case "escape":
                out.append("Esc")
            case "enter" | "return":
                out.append("Enter")
            case _ if lower.startswith("f") and lower[1:].isdigit():
                out.append(lower.upper())
            case _ if len(lower) == 1:
                out.append(lower.upper())
            case _:
                out.append(lower.capitalize())
    return "+".join(out)


def format_keys(keys: tuple[str, ...]) -> str:
    return " / ".join(format_key(k) for k in keys if k)
