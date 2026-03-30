from __future__ import annotations

import os
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

    Uses os.walk with directory pruning so excluded trees are never entered.
    Synchronous — call via asyncio.to_thread() from async code.
    """
    root_str = str(root.resolve())
    results: list[DiscoveredFile] = []

    for dirpath, dirnames, filenames in os.walk(root_str):
        # Prune excluded directories in-place (prevents descent)
        dirnames[:] = [d for d in dirnames if d not in _EXCLUDE_DIRS]

        rel_dir = os.path.relpath(dirpath, root_str)
        parts = Path(rel_dir).parts if rel_dir != "." else ()

        for fname in filenames:
            if not fname.endswith(".py"):
                continue
            rel = os.path.join(rel_dir, fname) if rel_dir != "." else fname
            boost = fname in _BOOST_NAMES or (len(parts) >= 1 and parts[0] in _BOOST_DIRS)
            results.append(DiscoveredFile(path=rel, boost=boost))

    results.sort(key=lambda f: (not f.boost, f.path))
    return results[:_MAX_RESULTS]
