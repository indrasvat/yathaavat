from __future__ import annotations

from dataclasses import dataclass

from yathaavat.core.commands import CommandRegistry
from yathaavat.core.services import ServiceRegistry
from yathaavat.core.ui_host import UiHost
from yathaavat.core.widgets import WidgetRegistry


@dataclass(frozen=True, slots=True)
class AppContext:
    commands: CommandRegistry
    widgets: WidgetRegistry
    services: ServiceRegistry
    host: UiHost
