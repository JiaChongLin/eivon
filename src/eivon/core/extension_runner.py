"""One-shot child process for untrusted deployment extension calls."""

from __future__ import annotations

import asyncio
import json
import sys

from .contracts import ExecutionContext, ToolResult
from .extensions import ExtensionRegistry


async def main(modules: tuple[str, ...]) -> None:
    registry = ExtensionRegistry(mode="trusted")
    registry.load(modules)
    line = await asyncio.to_thread(sys.stdin.buffer.readline)
    if not line:
        raise RuntimeError("Extension request is empty")
    request = json.loads(line)
    context = ExecutionContext.model_validate(request["context"])
    handler = registry.tools.get(request["entrypoint"])
    if handler is None:
        raise RuntimeError("Extension entrypoint is not registered")
    result = ToolResult.model_validate(await handler(request["arguments"], context))
    sys.stdout.write(result.model_dump_json() + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    asyncio.run(main(tuple(sys.argv[1:])))
