"""Versioned public contracts for resources, extensions, and execution."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResourceRef(Contract):
    id: str = Field(min_length=1, max_length=128)
    version: int = Field(ge=1)


class ModelSpec(Contract):
    provider: Literal["openai_compatible", "demo"] = "openai_compatible"
    model: str = Field(min_length=1, max_length=200)
    base_url: str = Field(default="https://api.openai.com/v1", max_length=2048)
    credential_id: str | None = None
    temperature: float = Field(default=0.3, ge=0, le=2)
    max_output_tokens: int = Field(default=2048, ge=1, le=32768)
    timeout_seconds: int = Field(default=60, ge=1, le=300)
    supports_tools: bool = True


class PromptSpec(Contract):
    template: str = Field(max_length=100_000)
    variables: dict[str, str] = Field(default_factory=dict)


class ToolSpec(Contract):
    description: str = Field(min_length=1, max_length=4000)
    input_schema: dict[str, Any] = Field(
        default_factory=lambda: {"type": "object", "properties": {}}
    )
    output_schema: dict[str, Any] | None = None
    adapter: Literal["builtin", "python", "http", "mcp"] = "builtin"
    entrypoint: str = Field(default="echo", max_length=200)
    config: dict[str, Any] = Field(default_factory=dict)
    credential_id: str | None = None
    effect: Literal["read", "write"] = "read"
    requires_approval: bool = False
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    max_result_bytes: int = Field(default=32_768, ge=256, le=1_048_576)


class SkillSpec(Contract):
    description: str = Field(min_length=1, max_length=4000)
    body: str = Field(min_length=1, max_length=200_000)
    references: dict[str, str] = Field(default_factory=dict)
    tool_refs: list[ResourceRef] = Field(default_factory=list, max_length=100)
    preload: bool = False


class BundleSpec(Contract):
    description: str = Field(default="", max_length=4000)
    tool_refs: list[ResourceRef] = Field(default_factory=list, max_length=100)
    skill_refs: list[ResourceRef] = Field(default_factory=list, max_length=100)
    prompt_refs: list[ResourceRef] = Field(default_factory=list, max_length=30)
    workflow_refs: list[ResourceRef] = Field(default_factory=list, max_length=50)
    knowledge_collection_ids: list[str] = Field(default_factory=list, max_length=50)
    context_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object"})


class ExecutionPolicy(Contract):
    max_iterations: int = Field(default=12, ge=1, le=50)
    timeout_seconds: int = Field(default=300, ge=5, le=3600)
    max_input_chars: int = Field(default=60_000, ge=1000, le=250_000)
    max_tool_calls: int = Field(default=30, ge=0, le=100)
    require_write_approval: bool = True


class AgentSpec(BundleSpec):
    model_ref: ResourceRef
    bundle_refs: list[ResourceRef] = Field(default_factory=list, max_length=50)
    policy: ExecutionPolicy = Field(default_factory=ExecutionPolicy)
    greeting: str = Field(default="How can I help?", max_length=2000)


class ToolStep(Contract):
    type: Literal["tool"] = "tool"
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    tool_ref: ResourceRef
    arguments: dict[str, Any] = Field(default_factory=dict)


class PromptStep(Contract):
    type: Literal["prompt"] = "prompt"
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    template: str = Field(min_length=1, max_length=60_000)
    model_ref: ResourceRef


class InputStep(Contract):
    type: Literal["input"] = "input"
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    question: str = Field(min_length=1, max_length=4000)
    input_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object"})


class ConditionStep(Contract):
    type: Literal["condition"] = "condition"
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    value_path: str = Field(max_length=200)
    equals: Any = None
    skip_step_ids: list[str] = Field(default_factory=list)


WorkflowStep = Annotated[
    ToolStep | PromptStep | InputStep | ConditionStep, Field(discriminator="type")
]


class WorkflowSpec(Contract):
    description: str = Field(default="", max_length=4000)
    input_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object"})
    steps: list[WorkflowStep] = Field(min_length=1, max_length=100)
    output_template: str = Field(default="{{steps}}", max_length=20_000)

    @model_validator(mode="after")
    def validate_steps(self) -> WorkflowSpec:
        ids = [s.id for s in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("Workflow step IDs must be unique")
        for position, step in enumerate(self.steps):
            if isinstance(step, ConditionStep) and not set(step.skip_step_ids).issubset(
                ids[position + 1 :]
            ):
                raise ValueError("Conditions may only skip later steps")
        return self


class ConnectionSpec(Contract):
    adapter: Literal["http", "mcp"] = "http"
    base_url: str = Field(min_length=1, max_length=2048)
    credential_id: str | None = None
    description: str = Field(default="", max_length=4000)
    timeout_seconds: int = Field(default=30, ge=1, le=120)


RESOURCE_SCHEMAS: dict[str, type[Contract]] = {
    "model": ModelSpec,
    "prompt": PromptSpec,
    "tool": ToolSpec,
    "skill": SkillSpec,
    "bundle": BundleSpec,
    "agent": AgentSpec,
    "workflow": WorkflowSpec,
    "connection": ConnectionSpec,
}
ResourceKind = Literal[
    "model", "prompt", "tool", "skill", "bundle", "agent", "workflow", "connection"
]


class ToolCall(Contract):
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResult(Contract):
    success: bool
    data: Any = None
    error: str | None = None
    completeness: Literal["complete", "partial", "empty", "truncated"] = "complete"
    artifacts: list[dict[str, Any]] = Field(default_factory=list)


class ModelMessage(Contract):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_call_id: str | None = None


class ModelResponse(Contract):
    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: dict[str, int] = Field(default_factory=dict)


class ExecutionContext(Contract):
    workspace_id: str
    principal_id: str
    session_id: str | None = None
    run_id: str
    business_context: dict[str, Any] = Field(default_factory=dict)
