from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from importlib import metadata
from typing import Any, Protocol, runtime_checkable

from yathaavat.core.app_context import AppContext


class Plugin(ABC):
    @property
    @abstractmethod
    def id(self) -> str: ...

    @abstractmethod
    def register(self, ctx: AppContext) -> None: ...


@runtime_checkable
class PluginFactory(Protocol):
    def __call__(self) -> Plugin: ...


@dataclass(frozen=True, slots=True)
class PluginLoadError:
    plugin_name: str
    error: Exception


class PluginManager:
    def __init__(self, *, group: str = "yathaavat.plugins") -> None:
        self._group = group

    def load(self) -> tuple[list[Plugin], list[PluginLoadError]]:
        plugins: list[Plugin] = []
        errors: list[PluginLoadError] = []

        for ep in metadata.entry_points(group=self._group):
            try:
                loaded: Any = ep.load()
                plugin = self._coerce_plugin(ep.name, loaded)
                plugins.append(plugin)
            except Exception as exc:
                errors.append(PluginLoadError(plugin_name=ep.name, error=exc))

        plugins.sort(key=lambda p: p.id)
        return plugins, errors

    def _coerce_plugin(self, name: str, loaded: Any) -> Plugin:
        match loaded:
            case Plugin():
                return loaded
            case type() as cls if issubclass(cls, Plugin):
                return cls()
            case PluginFactory() as factory:
                return factory()
            case _:
                msg = (
                    f"Entry point '{name}' did not return a Plugin/Plugin factory "
                    f"(got {type(loaded)!r})"
                )
                raise TypeError(msg)
