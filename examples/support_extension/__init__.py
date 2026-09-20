"""Synthetic customer-support extension showing a second domain bundle."""

from eivon.core.contracts import ExecutionContext, ToolResult


async def lookup_case(arguments: dict, context: ExecutionContext) -> ToolResult:
    case_id = str(arguments.get("case_id", "unknown"))
    return ToolResult(
        success=True,
        data={
            "case_id": case_id,
            "priority": "normal",
            "status": "open",
            "workspace": context.workspace_id,
        },
    )


def register(registry):
    registry.register_tool("lookup_case", lookup_case)
