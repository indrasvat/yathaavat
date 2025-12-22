from __future__ import annotations

from yathaavat.core.app_context import AppContext
from yathaavat.core.commands import Command, CommandRegistry, CommandSpec
from yathaavat.core.plugins import Plugin, PluginManager
from yathaavat.core.processes import ProcessDiscovery, ProcessInfo
from yathaavat.core.services import ServiceKey, ServiceRegistry
from yathaavat.core.session import (
    SESSION_MANAGER,
    SESSION_STORE,
    BreakpointInfo,
    FrameInfo,
    RunToCursorManager,
    SafeAttachManager,
    SessionManager,
    SessionSnapshot,
    SessionState,
    SessionStore,
    SilentEvaluateManager,
    ThreadInfo,
    VariableInfo,
    VariablesManager,
    WatchInfo,
)
from yathaavat.core.ui_host import NullUiHost, UiHost
from yathaavat.core.widgets import Slot, WidgetContribution, WidgetRegistry

__all__ = [
    "SESSION_MANAGER",
    "SESSION_STORE",
    "AppContext",
    "BreakpointInfo",
    "Command",
    "CommandRegistry",
    "CommandSpec",
    "FrameInfo",
    "NullUiHost",
    "Plugin",
    "PluginManager",
    "ProcessDiscovery",
    "ProcessInfo",
    "RunToCursorManager",
    "SafeAttachManager",
    "ServiceKey",
    "ServiceRegistry",
    "SessionManager",
    "SessionSnapshot",
    "SessionState",
    "SessionStore",
    "SilentEvaluateManager",
    "Slot",
    "ThreadInfo",
    "UiHost",
    "VariableInfo",
    "VariablesManager",
    "WatchInfo",
    "WidgetContribution",
    "WidgetRegistry",
]
