"""Run worker that executes immutable Agent release snapshots."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from eivon.adapters.models import CompatibleModel, DemoModel, ModelUnavailable
from eivon.core.contracts import (
    ExecutionContext,
    ExecutionPolicy,
    ModelMessage,
    ModelSpec,
    ToolCall,
)
from eivon.core.engine import (
    AgentEngine,
    BudgetExceeded,
    EngineState,
    ExecutionCancelled,
    PauseExecution,
)

from .artifacts import Artifacts
from .db import Database
from .evaluations import Evaluations
from .knowledge import Knowledge
from .runs import LeaseLost, Runs
from .security import Security
from .settings import Settings
from .tool_runtime import ToolRuntime, tool_name


class RunWorker:
    def __init__(
        self,
        database: Database,
        runs: Runs,
        settings: Settings,
        security: Security,
        artifacts: Artifacts,
        extensions,
        knowledge: Knowledge | None = None,
        worker_id: str | None = None,
    ):
        self.database, self.runs, self.settings, self.security = database, runs, settings, security
        self.artifacts, self.extensions, self.knowledge = artifacts, extensions, knowledge
        self.worker_id = worker_id or f"worker-{os.getpid()}"
        self.evaluations = Evaluations(database, runs)

    async def once(self) -> bool:
        scored = self.evaluations.reconcile()
        item = self.runs.claim(self.worker_id, self.settings.lease_seconds)
        if item is None:
            return bool(scored)
        try:
            await self.execute(item)
        except LeaseLost:
            return True
        except Exception as exc:  # final execution boundary
            try:
                self.runs.finish(
                    item["id"],
                    self.worker_id,
                    "failed",
                    error=f"Execution failed ({type(exc).__name__})",
                )
            except Exception:
                pass
        self.evaluations.reconcile()
        return True

    async def loop(self, stop: asyncio.Event | None = None):
        stop = stop or asyncio.Event()
        while not stop.is_set():
            if not await self.once():
                try:
                    await asyncio.wait_for(stop.wait(), timeout=self.settings.worker_poll_seconds)
                except asyncio.TimeoutError:
                    pass

    async def execute(self, item: dict[str, Any]):
        snapshot = item["snapshot"]
        root = snapshot["root"]
        if root["kind"] == "workflow":
            await self._execute_workflow(item)
            return
        if root["kind"] != "agent":
            self.runs.finish(
                item["id"],
                self.worker_id,
                "failed",
                error="Only Agent execution is supported by this worker",
            )
            return
        context = ExecutionContext(
            workspace_id=item["workspace_id"],
            principal_id=item["user_id"],
            session_id=item.get("session_id"),
            run_id=item["id"],
            business_context=item.get("business_context", {}),
        )
        resources = snapshot.get("resources", {})
        model_resource = resources.get(
            f"{root['spec']['model_ref']['id']}@{root['spec']['model_ref']['version']}"
        )
        if model_resource is None:
            raise RuntimeError("Agent model dependency is missing from the release snapshot")
        model_spec = ModelSpec.model_validate(model_resource["spec"])
        credential = self.security.credential_value(item["workspace_id"], model_spec.credential_id)
        if model_spec.provider == "demo":
            model = DemoModel()
        else:
            model = CompatibleModel(model_spec, credential, self.settings.allowed_hosts)
        decisions = dict(item.get("checkpoint", {}).get("decisions", {}))
        resume = item.get("checkpoint", {}).get("resume_response")
        waiting = item.get("checkpoint", {}).get("waiting", {})
        if resume and isinstance(resume, dict) and waiting.get("approval_key"):
            decisions[waiting["approval_key"]] = bool(resume.get("approved"))

        async def emit_event(kind, data):
            self._emit(item["id"], kind, data)

        tool_runtime = ToolRuntime(
            snapshot=snapshot,
            context=context,
            settings=self.settings,
            security=self.security,
            artifacts=self.artifacts,
            extensions=self.extensions,
            decisions=decisions,
            require_write_approval=root["spec"]["policy"]["require_write_approval"],
            emit=emit_event,
            knowledge_search=self.knowledge.search_for_run if self.knowledge else None,
        )
        messages = self._initial_messages(root["spec"], resources, item)
        checkpoint = item.get("checkpoint", {})
        if checkpoint.get("engine_state"):
            state = EngineState.model_validate(checkpoint["engine_state"])
            # Approval resume state contains the already emitted tool call; continue it.
            state.pending_calls = (
                [state.pending_calls[state.pending_index]]
                if state.pending_index < len(state.pending_calls)
                else state.pending_calls
            )
            state.pending_index = 0
        else:
            state = EngineState(messages=messages)
        policy = ExecutionPolicy.model_validate(root["spec"]["policy"])
        engine = AgentEngine(model, tool_runtime, tool_runtime.definitions(), policy)

        async def emit(kind, data):
            self._emit(item["id"], kind, data)

        async def save(value):
            self.runs.save_checkpoint(
                item["id"],
                self.worker_id,
                {"engine_state": value.model_dump(mode="json"), "decisions": decisions},
                value.usage,
            )

        async def cancelled():
            return self.runs.cancelled(item["id"], self.worker_id)

        heartbeat = asyncio.create_task(self._heartbeat(item["id"]))
        try:
            result = await engine.run(state, emit, save, cancelled)
            self.runs.finish(
                item["id"],
                self.worker_id,
                "completed",
                output={"text": result.output, "usage": result.usage},
                checkpoint={},
            )
        except PauseExecution as pause:
            checkpoint = {
                "engine_state": state.model_dump(mode="json"),
                "decisions": decisions,
                "waiting": pause.payload,
            }
            self.runs.finish(
                item["id"],
                self.worker_id,
                pause.status,
                checkpoint=checkpoint,
                output={"text": state.output},
            )
        except ExecutionCancelled:
            self.runs.finish(
                item["id"],
                self.worker_id,
                "cancelled",
                output={"text": state.output},
                checkpoint={},
            )
        except BudgetExceeded as exc:
            self.runs.finish(
                item["id"],
                self.worker_id,
                "failed",
                error=str(exc),
                output={"text": state.output},
                checkpoint={},
            )
        except (ModelUnavailable, TimeoutError) as exc:
            self.runs.finish(
                item["id"],
                self.worker_id,
                "failed",
                error=str(exc),
                output={"text": state.output},
                checkpoint={},
            )
        finally:
            heartbeat.cancel()
            try:
                await heartbeat
            except asyncio.CancelledError:
                pass

    async def _execute_workflow(self, item: dict[str, Any]):
        """Execute the portable baseline workflow steps with the same Run controls."""
        snapshot, root = item["snapshot"], item["snapshot"]["root"]
        resources = snapshot.get("resources", {})
        context = ExecutionContext(
            workspace_id=item["workspace_id"],
            principal_id=item["user_id"],
            session_id=item.get("session_id"),
            run_id=item["id"],
            business_context=item.get("business_context", {}),
        )
        checkpoint = item.get("checkpoint", {})
        decisions = dict(checkpoint.get("decisions", {}))
        waiting, resume = checkpoint.get("waiting", {}), checkpoint.get("resume_response")
        if resume and waiting.get("approval_key"):
            decisions[waiting["approval_key"]] = bool(resume.get("approved"))
        saved = checkpoint.get("workflow_state", {})
        index, results = int(saved.get("index", 0)), dict(saved.get("results", {}))
        if resume and waiting.get("kind") == "input" and waiting.get("step_id"):
            results[waiting["step_id"]] = resume
            index += 1

        async def emit_event(kind, data):
            self._emit(item["id"], kind, data)

        tool_runtime = ToolRuntime(
            snapshot=snapshot,
            context=context,
            settings=self.settings,
            security=self.security,
            artifacts=self.artifacts,
            extensions=self.extensions,
            decisions=decisions,
            emit=emit_event,
            knowledge_search=self.knowledge.search_for_run if self.knowledge else None,
        )
        model = None
        for step in root["spec"]["steps"]:
            if step["type"] == "prompt":
                reference = step["model_ref"]
                model_resource = resources.get(f"{reference['id']}@{reference['version']}")
                if model_resource:
                    spec = ModelSpec.model_validate(model_resource["spec"])
                    credential = self.security.credential_value(
                        item["workspace_id"], spec.credential_id
                    )
                    model = (
                        DemoModel()
                        if spec.provider == "demo"
                        else CompatibleModel(spec, credential, self.settings.allowed_hosts)
                    )
                break
        steps = root["spec"]["steps"]
        heartbeat = asyncio.create_task(self._heartbeat(item["id"]))
        try:
            while index < len(steps):
                if self.runs.cancelled(item["id"], self.worker_id):
                    raise ExecutionCancelled()
                step = steps[index]
                if step["type"] == "condition":
                    value = results.get(step["value_path"].split(".")[-1])
                    if value == step.get("equals"):
                        skip = set(step.get("skip_step_ids", []))
                        index = next(
                            (
                                pos
                                for pos, candidate in enumerate(steps)
                                if pos > index and candidate["id"] in skip
                            ),
                            index + 1,
                        )
                        continue
                elif step["type"] == "input":
                    raise PauseExecution(
                        "waiting_input",
                        {
                            "kind": "input",
                            "step_id": step["id"],
                            "question": step["question"],
                            "input_schema": step["input_schema"],
                        },
                    )
                elif step["type"] == "tool":
                    ref = step["tool_ref"]
                    resource = resources.get(f"{ref['id']}@{ref['version']}")
                    if not resource:
                        raise RuntimeError("Workflow tool dependency is missing")
                    result = await tool_runtime.invoke(
                        ToolCall(
                            id=step["id"],
                            name=tool_name(resource),
                            arguments=step.get("arguments", {}),
                        )
                    )
                    results[step["id"]] = result.model_dump(mode="json")
                elif step["type"] == "prompt":
                    if model is None:
                        raise RuntimeError("Workflow prompt step has no model")
                    message = step["template"].replace(
                        "{{steps}}", json.dumps(results, ensure_ascii=False)
                    )
                    response = await model.complete(
                        [ModelMessage(role="user", content=message)],
                        tool_runtime.definitions(),
                        emit_event,
                    )
                    results[step["id"]] = {"text": response.content, "usage": response.usage}
                index += 1
                self.runs.save_checkpoint(
                    item["id"],
                    self.worker_id,
                    {
                        "workflow_state": {"index": index, "results": results},
                        "decisions": decisions,
                    },
                )
            self.runs.finish(
                item["id"],
                self.worker_id,
                "completed",
                output={"text": json.dumps(results, ensure_ascii=False), "steps": results},
                checkpoint={},
            )
        except PauseExecution as pause:
            self.runs.finish(
                item["id"],
                self.worker_id,
                pause.status,
                checkpoint={
                    "workflow_state": {"index": index, "results": results},
                    "decisions": decisions,
                    "waiting": pause.payload,
                },
                output={"steps": results},
            )
        except ExecutionCancelled:
            self.runs.finish(
                item["id"], self.worker_id, "cancelled", output={"steps": results}, checkpoint={}
            )
        except Exception as exc:
            self.runs.finish(
                item["id"],
                self.worker_id,
                "failed",
                error=f"Workflow failed ({type(exc).__name__})",
                output={"steps": results},
                checkpoint={},
            )
        finally:
            heartbeat.cancel()
            try:
                await heartbeat
            except asyncio.CancelledError:
                pass

    def _initial_messages(
        self, agent_spec: dict, resources: dict, item: dict
    ) -> list[ModelMessage]:
        system_parts = [
            "You are an agent running inside Eivon. Follow the configured tools, skills and execution policy. Use current tool results as evidence."
        ]
        for ref in agent_spec.get("prompt_refs", []):
            prompt = resources.get(f"{ref['id']}@{ref['version']}")
            if prompt:
                system_parts.append(prompt["spec"]["template"])
        system_parts.append(
            "Business context (trusted by the host): " + str(item.get("business_context", {}))
        )
        messages = [ModelMessage(role="system", content="\n\n".join(system_parts))]
        for history in item.get("history", []):
            messages.append(ModelMessage.model_validate(history))
        messages.append(ModelMessage(role="user", content=str(item["input"].get("message", ""))))
        return messages

    def _emit(self, run_id: str, kind: str, data: dict):
        try:
            self.runs.emit(run_id, self.worker_id, kind, data)
        except LeaseLost:
            raise

    async def _heartbeat(self, run_id: str):
        while True:
            await asyncio.sleep(max(1, self.settings.lease_seconds // 3))
            if not self.runs.heartbeat(run_id, self.worker_id, self.settings.lease_seconds):
                return
