import asyncio
import textwrap
from pathlib import Path

import pytest

from eivon.core.contracts import ExecutionContext
from eivon.core.extensions import ExtensionRegistry


def write_extension(path: Path):
    path.write_text(
        textwrap.dedent("""
        from eivon.core.contracts import ToolResult
        async def upper(arguments, context):
            return ToolResult(success=True, data={"value": arguments["value"].upper(), "run": context.run_id})
        async def slow(arguments, context):
            import asyncio
            await asyncio.sleep(10)
            return ToolResult(success=True, data={"done": True})
        def register(registry):
            registry.register_tool("upper", upper)
            registry.register_tool("slow", slow)
    """)
    )


def context():
    return ExecutionContext(workspace_id="w", principal_id="u", run_id="r")


def test_process_extension_executes_without_parent_import(tmp_path, monkeypatch):
    module = tmp_path / "sample_extension.py"
    write_extension(module)
    monkeypatch.syspath_prepend(str(tmp_path))
    registry = ExtensionRegistry(mode="process")
    registry.load(("sample_extension",))
    assert registry.tools == {}
    result = asyncio.run(registry.invoke("upper", {"value": "hello"}, context(), 2))
    assert result.data == {"value": "HELLO", "run": "r"}


def test_process_extension_timeout_kills_child(tmp_path, monkeypatch):
    module = tmp_path / "slow_extension.py"
    write_extension(module)
    monkeypatch.syspath_prepend(str(tmp_path))
    registry = ExtensionRegistry(mode="process")
    registry.load(("slow_extension",))
    with pytest.raises(TimeoutError):
        asyncio.run(registry.invoke("slow", {}, context(), 0.05))
