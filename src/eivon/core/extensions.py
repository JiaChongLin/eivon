"""Deployment extension registry with trusted or isolated subprocess execution."""

from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import os
import signal
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from .contracts import ExecutionContext, ToolResult

ToolHandler = Callable[[dict[str, Any], ExecutionContext], Awaitable[ToolResult]]


@dataclass
class ExtensionRegistry:
    mode: str = "trusted"
    tools: dict[str, ToolHandler] = field(default_factory=dict)
    packages: list[dict[str, Any]] = field(default_factory=list)
    modules: tuple[str, ...] = ()

    def register_tool(self, name: str, handler: ToolHandler) -> None:
        if self.mode == "process":
            raise RuntimeError("Process-isolated extensions must register in their runner")
        if name in self.tools:
            raise ValueError(f"Duplicate extension tool: {name}")
        if not inspect.iscoroutinefunction(handler):
            raise TypeError("Extension handlers must be async and cooperate with cancellation")
        self.tools[name] = handler

    def load(self, modules: tuple[str, ...]) -> None:
        self.modules = modules
        if self.mode == "process":
            self.packages.extend({"module": name, "version": "isolated"} for name in modules)
            return
        for name in modules:
            module = importlib.import_module(name)
            register = getattr(module, "register", None)
            if not callable(register):
                raise ValueError(f"Extension {name} must export register(registry)")
            register(self)
            self.packages.append(
                {"module": name, "version": str(getattr(module, "__version__", "unversioned"))}
            )

    async def invoke(
        self, name: str, arguments: dict[str, Any], context: ExecutionContext, timeout: int
    ) -> ToolResult:
        if self.mode == "trusted":
            handler = self.tools.get(name)
            if handler is None:
                raise ValueError(
                    "Python extension is not installed by the deployment administrator"
                )
            return ToolResult.model_validate(await handler(arguments, context))
        if not self.modules:
            raise ValueError("No isolated extension modules are configured")
        request = json.dumps(
            {"entrypoint": name, "arguments": arguments, "context": context.model_dump()},
            ensure_ascii=False,
        )
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "eivon.core.extension_runner",
            *self.modules,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
            env={
                **os.environ,
                "PYTHONPATH": os.pathsep.join(sys.path)
                + os.pathsep
                + os.environ.get("PYTHONPATH", ""),
            },
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate((request + "\n").encode()), timeout=timeout
            )
        except (TimeoutError, asyncio.CancelledError):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await process.wait()
            raise
        if process.returncode != 0:
            detail = stderr.decode(errors="replace")[:500]
            raise RuntimeError(f"Isolated extension failed: {detail or 'runner exited'}")
        try:
            return ToolResult.model_validate(json.loads(stdout.decode()))
        except (ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError("Isolated extension returned invalid JSON") from exc
