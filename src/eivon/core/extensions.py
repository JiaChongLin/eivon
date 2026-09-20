"""Trusted deployment-time Python extensions with explicit public registration."""

from __future__ import annotations

import importlib
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from .contracts import ExecutionContext, ToolResult

ToolHandler = Callable[[dict[str, Any], ExecutionContext], Awaitable[ToolResult]]


@dataclass
class ExtensionRegistry:
    tools: dict[str, ToolHandler] = field(default_factory=dict)
    packages: list[dict[str, Any]] = field(default_factory=list)

    def register_tool(self, name: str, handler: ToolHandler) -> None:
        if name in self.tools:
            raise ValueError(f"Duplicate extension tool: {name}")
        if not inspect.iscoroutinefunction(handler):
            raise TypeError("Extension handlers must be async and cooperate with cancellation")
        self.tools[name] = handler

    def load(self, modules: tuple[str, ...]) -> None:
        for name in modules:
            module = importlib.import_module(name)
            register = getattr(module, "register", None)
            if not callable(register):
                raise ValueError(f"Extension {name} must export register(registry)")
            register(self)
            self.packages.append(
                {"module": name, "version": str(getattr(module, "__version__", "unversioned"))}
            )
