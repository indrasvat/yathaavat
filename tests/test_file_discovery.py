from __future__ import annotations

from pathlib import Path

from yathaavat.app.file_discovery import discover_python_files


def _create_file(base: Path, relpath: str) -> None:
    p = base / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# test\n", encoding="utf-8")


def test_discovers_py_files(tmp_path: Path) -> None:
    _create_file(tmp_path, "app.py")
    _create_file(tmp_path, "lib/utils.py")
    results = discover_python_files(tmp_path)
    paths = [f.path for f in results]
    assert "app.py" in paths
    assert "lib/utils.py" in paths


def test_excludes_venv(tmp_path: Path) -> None:
    _create_file(tmp_path, "app.py")
    _create_file(tmp_path, ".venv/lib/site.py")
    results = discover_python_files(tmp_path)
    paths = [f.path for f in results]
    assert "app.py" in paths
    assert ".venv/lib/site.py" not in paths


def test_excludes_pycache(tmp_path: Path) -> None:
    _create_file(tmp_path, "app.py")
    _create_file(tmp_path, "__pycache__/app.cpython-314.pyc.py")
    results = discover_python_files(tmp_path)
    paths = [f.path for f in results]
    assert all("__pycache__" not in p for p in paths)


def test_boosts_entrypoints(tmp_path: Path) -> None:
    _create_file(tmp_path, "main.py")
    _create_file(tmp_path, "zebra.py")
    _create_file(tmp_path, "examples/demo.py")
    results = discover_python_files(tmp_path)
    assert results[0].boost is True
    assert results[0].path in ("main.py", "examples/demo.py")


def test_relative_paths(tmp_path: Path) -> None:
    _create_file(tmp_path, "src/mod/core.py")
    results = discover_python_files(tmp_path)
    paths = [f.path for f in results]
    assert "src/mod/core.py" in paths
    assert not any(str(tmp_path) in p for p in paths)


def test_caps_results(tmp_path: Path) -> None:
    for i in range(600):
        _create_file(tmp_path, f"gen/mod{i:04d}.py")
    results = discover_python_files(tmp_path)
    assert len(results) <= 500
