from __future__ import annotations

__all__ = ["__version__"]

try:
    from yathaavat._version import __version__
except ModuleNotFoundError:
    __version__ = "0.0.0+unknown"
