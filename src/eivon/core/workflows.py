"""Data-only workflow bindings. No expression evaluation or attribute access."""

from __future__ import annotations

import json
import re
from typing import Any

_BINDING = re.compile(r"\{\{\s*([a-zA-Z0-9_.-]+)\s*\}\}")


class WorkflowBindingError(ValueError):
    pass


def resolve_path(path: str, scope: dict[str, Any]) -> Any:
    parts = path.split(".")
    if not parts or parts[0] not in {"input", "context", "steps"}:
        raise WorkflowBindingError("Workflow paths must start with input, context or steps")
    value: Any = scope
    for part in parts:
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and part.isdecimal() and int(part) < len(value):
            value = value[int(part)]
        else:
            raise WorkflowBindingError(f"Workflow value is unavailable: {path}")
    return value


def as_text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def render_text(template: str, scope: dict[str, Any]) -> str:
    return _BINDING.sub(lambda match: as_text(resolve_path(match[1], scope)), template)


def bind_arguments(value: Any, scope: dict[str, Any]) -> Any:
    """Whole placeholders preserve JSON types; inline placeholders produce text."""
    if isinstance(value, dict):
        return {key: bind_arguments(child, scope) for key, child in value.items()}
    if isinstance(value, list):
        return [bind_arguments(child, scope) for child in value]
    if isinstance(value, str):
        match = _BINDING.fullmatch(value)
        return resolve_path(match[1], scope) if match else render_text(value, scope)
    return value


def json_equal(left: Any, right: Any) -> bool:
    """JSON booleans differ from numbers, including inside nested containers."""
    if type(left) in {int, float} and type(right) in {int, float}:
        return left == right
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(
            json_equal(value, right[key]) for key, value in left.items()
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            json_equal(a, b) for a, b in zip(left, right, strict=True)
        )
    return left == right
