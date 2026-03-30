"""Demo script with various exception types for testing the Exception panel.

Usage:
    # Launch under debugpy (yathaavat connects via Ctrl+K):
    python -m debugpy --listen 127.0.0.1:5678 --wait-for-client examples/demo_exceptions.py [N]

    # Or launch directly from yathaavat via Ctrl+R:
    examples/demo_exceptions.py [N]

Pass a scenario number 1-5 as argument, or run interactively.
"""

from __future__ import annotations

import sys


def simple_exception() -> None:
    """Raises a simple ValueError."""
    data = {"amount": "not-a-number"}
    total = int(data["amount"])  # ValueError here
    print(f"Total: {total}")


def chained_exception() -> None:
    """Raises a RuntimeError chained from a ConnectionError."""
    try:
        raise ConnectionError("database connection timeout")
    except ConnectionError as e:
        raise RuntimeError("failed to process order") from e


def implicit_chain() -> None:
    """Raises a TypeError during handling of a KeyError."""
    try:
        data: dict[str, object] = {}
        _ = data["missing_key"]
    except KeyError:
        raise TypeError("wrong type during error recovery")  # noqa: B904


def exception_group() -> None:
    """Raises an ExceptionGroup with mixed sub-exceptions."""
    errors: list[Exception] = [
        ValueError("invalid amount"),
        ConnectionError("db timeout"),
    ]
    raise ExceptionGroup("multiple failures", errors)


def nested_exception_group() -> None:
    """Raises a nested ExceptionGroup."""
    inner = ExceptionGroup(
        "inner group",
        [TypeError("wrong type"), OSError("disk full")],
    )
    raise ExceptionGroup(
        "outer group",
        [ValueError("bad value"), inner],
    )


def main() -> None:
    demos = {
        "1": ("Simple ValueError", simple_exception),
        "2": ("Chained exception (raise X from Y)", chained_exception),
        "3": ("Implicit chain (during handling)", implicit_chain),
        "4": ("ExceptionGroup (flat)", exception_group),
        "5": ("Nested ExceptionGroup", nested_exception_group),
    }

    # Accept scenario number as CLI argument for non-interactive use.
    if len(sys.argv) > 1:
        choice = sys.argv[1].strip()
    else:
        print("Exception demo — choose a scenario:")
        for key, (desc, _) in demos.items():
            print(f"  {key}: {desc}")
        print()
        choice = input("Enter choice [1-5]: ").strip()

    if choice not in demos:
        print(f"Unknown choice: {choice!r}")
        sys.exit(1)

    desc, func = demos[choice]
    print(f"Running: {desc}")
    func()


if __name__ == "__main__":
    main()
