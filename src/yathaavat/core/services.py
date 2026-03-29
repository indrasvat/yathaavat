from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypeVar

T = TypeVar("T", bound=object)


@dataclass(frozen=True, slots=True)
class ServiceKey[T]:
    id: str


@dataclass(frozen=True, slots=True)
class ServiceRegistrationError(Exception):
    key: ServiceKey[Any]
    message: str

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.key.id}: {self.message}"


class ServiceRegistry:
    def __init__(self) -> None:
        self._services: dict[ServiceKey[Any], object] = {}

    def register(self, key: ServiceKey[T], implementation: T) -> None:
        if key in self._services:
            raise ServiceRegistrationError(key=key, message="already registered")
        self._services[key] = implementation

    def get(self, key: ServiceKey[T]) -> T:
        try:
            implementation = self._services[key]
        except KeyError as exc:
            raise KeyError(f"Unknown service: {key.id}") from exc
        return implementation  # type: ignore[return-value]
