from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_EXCLUDE_DIRS = frozenset(
    {
        ".venv",
        "venv",
        "__pycache__",
        "site-packages",
        ".git",
        "node_modules",
        "build",
        "dist",
        ".tox",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        ".eggs",
        ".nox",
    }
)

_BOOST_NAMES = frozenset(
    {
        "main.py",
        "app.py",
        "manage.py",
        "__main__.py",
        "cli.py",
        "server.py",
        "worker.py",
        "run.py",
    }
)

_BOOST_DIRS = frozenset(
    {
        "examples",
        "scripts",
        "bin",
    }
)

_MAX_RESULTS = 500


@dataclass(frozen=True, slots=True)
class DiscoveredFile:
    path: str
    boost: bool


def discover_python_files(root: Path) -> list[DiscoveredFile]:
    """Discover .py files under root, excluding common non-source directories.

    Synchronous — call via asyncio.to_thread() from async code.
    """
    root = root.resolve()
    results: list[DiscoveredFile] = []

    for p in root.rglob("*.py"):
        rel = p.relative_to(root)
        parts = rel.parts

        if any(part in _EXCLUDE_DIRS for part in parts):
            continue

        boost = rel.name in _BOOST_NAMES or (len(parts) >= 2 and parts[0] in _BOOST_DIRS)
        results.append(DiscoveredFile(path=str(rel), boost=boost))

        if len(results) >= _MAX_RESULTS:
            break

    results.sort(key=lambda f: (not f.boost, f.path))
    return results
