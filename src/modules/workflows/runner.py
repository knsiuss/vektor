import json
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.identity.principal import Principal
from modules.knowledge.repository import KnowledgeRepository
from modules.model_gateway.base import LLMProvider
from modules.model_gateway.schemas import ChatMessage, ModelRequest
from modules.tools.registry import ToolRegistry
from modules.workflows.models import WorkflowDefinition, WorkflowRun
from modules.workflows.repository import WorkflowRepository
from modules.workflows.schemas import WorkflowRunOut, WorkflowStep, WorkflowStepLog

_TEMPLATE_VAR_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_.-]+)\s*\}\}")


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _render_template(template: str, ctx: dict[str, Any]) -> str:
    def _replace(match: re.Match[str]) -> str:
        path = match.group(1).split(".")
        cur: Any = ctx
        for part in path:
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return ""
        return str(cur)

    return _TEMPLATE_VAR_RE.sub(_replace, template)


def _render_dict(raw: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    rendered: dict[str, Any] = {}
    for key, value in raw.items():
        if isinstance(value, str):
            rendered[key] = _render_template(value, ctx)
        elif isinstance(value, dict):
            rendered[key] = _render_dict(value, ctx)
        else:
            rendered[key] = value
    return rendered


class WorkflowRunner:
    """Sequential workflow executor with pause/resume human approval checkpoints."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        principal: Principal,
        knowledge_repo: KnowledgeRepository,
        llm_provider: LLMProvider,
        tool_registry: ToolRegistry,
    ) -> None:
        self._session = session
        self._principal = principal
        self._repo = WorkflowRepository(session=session, principal=principal)
        self._knowledge = knowledge_repo
        self._llm = llm_provider
        self._tools = tool_registry

    async def start_run(
        self,
        workflow: WorkflowDefinition,
        *,
        input_data: dict[str, Any],
    ) -> WorkflowRunOut:
        run = WorkflowRun(
            workflow_id=workflow.id,
            tenant_id=self._principal.tenant_id,
            triggered_by=self._principal.user_id,
            status="running",
            current_step_index=0,
            input_json=json.dumps(input_data),
            context_json=json.dumps({"input": input_data, "steps": {}}),
            step_logs_json="[]",
        )
        self._session.add(run)
        await self._session.flush()
        return await self._execute_from_current(workflow, run)

    async def resume_run(
        self,
        run: WorkflowRun,
        workflow: WorkflowDefinition,
        *,
        decision: str,
        comment: str | None = None,
    ) -> WorkflowRunOut:
        if run.status != "waiting_approval":
            raise ValueError(f"Workflow run is not waiting for approval (status={run.status}).")

        logs = [WorkflowStepLog.model_validate(item) for item in json.loads(run.step_logs_json)]
        ctx: dict[str, Any] = json.loads(run.context_json)
        steps = [WorkflowStep.model_validate(item) for item in json.loads(workflow.steps_json)]
        current_step = steps[run.current_step_index]
        now = _utc_now()

        if decision == "reject":
            if logs:
                logs[-1].status = "rejected"
                logs[-1].output = comment or "Rejected by reviewer."
                logs[-1].finished_at = now
            run.status = "rejected"
            run.finished_at = now
            run.step_logs_json = json.dumps([log.model_dump(mode="json") for log in logs])
            await self._session.flush()
            return self._repo.to_run_out(run, workflow.name)

        if logs:
            logs[-1].status = "approved"
            logs[-1].output = comment or f"Approved by {self._principal.user_id}."
            logs[-1].finished_at = now
        ctx.setdefault("steps", {})[current_step.id] = {
            "output": comment or "approved",
            "approved_by": self._principal.user_id,
        }
        run.context_json = json.dumps(ctx)
        run.step_logs_json = json.dumps([log.model_dump(mode="json") for log in logs])
        run.current_step_index += 1
        run.status = "running"
        await self._session.flush()
        return await self._execute_from_current(workflow, run)

    async def _execute_from_current(
        self,
        workflow: WorkflowDefinition,
        run: WorkflowRun,
    ) -> WorkflowRunOut:
        steps = [WorkflowStep.model_validate(item) for item in json.loads(workflow.steps_json)]
        ctx: dict[str, Any] = json.loads(run.context_json)
        logs = [WorkflowStepLog.model_validate(item) for item in json.loads(run.step_logs_json)]

        while run.current_step_index < len(steps):
            step = steps[run.current_step_index]
            started = _utc_now()

            if step.type == "human_approval":
                msg = _render_template(
                    step.message_template or "Approval required to continue workflow.",
                    ctx,
                )
                logs.append(
                    WorkflowStepLog(
                        step_id=step.id,
                        step_name=step.name,
                        step_type=step.type,
                        status="waiting_approval",
                        output=msg,
                        started_at=started,
                    )
                )
                run.status = "waiting_approval"
                run.context_json = json.dumps(ctx)
                run.step_logs_json = json.dumps([log.model_dump(mode="json") for log in logs])
                await self._session.flush()
                return self._repo.to_run_out(run, workflow.name)

            try:
                output = await self._run_step_with_retry(step, ctx, run_id=run.id)
                finished = _utc_now()
                ctx.setdefault("steps", {})[step.id] = {"output": output}
                logs.append(
                    WorkflowStepLog(
                        step_id=step.id,
                        step_name=step.name,
                        step_type=step.type,
                        status="completed",
                        output=output[:4000],
                        started_at=started,
                        finished_at=finished,
                    )
                )
                run.current_step_index += 1
            except Exception as exc:
                finished = _utc_now()
                logs.append(
                    WorkflowStepLog(
                        step_id=step.id,
                        step_name=step.name,
                        step_type=step.type,
                        status="failed",
                        error=str(exc),
                        started_at=started,
                        finished_at=finished,
                    )
                )
                run.status = "failed"
                run.error_message = str(exc)
                run.finished_at = finished
                run.context_json = json.dumps(ctx)
                run.step_logs_json = json.dumps([log.model_dump(mode="json") for log in logs])
                await self._session.flush()
                return self._repo.to_run_out(run, workflow.name)

        run.status = "completed"
        run.finished_at = _utc_now()
        run.context_json = json.dumps(ctx)
        run.step_logs_json = json.dumps([log.model_dump(mode="json") for log in logs])
        await self._session.flush()
        return self._repo.to_run_out(run, workflow.name)

    async def _run_step_with_retry(
        self,
        step: WorkflowStep,
        ctx: dict[str, Any],
        *,
        run_id: str,
    ) -> str:
        last_exc: Exception | None = None
        for _attempt in range(step.max_retries + 1):
            try:
                return await self._execute_single_step(step, ctx, run_id=run_id)
            except Exception as exc:
                last_exc = exc
        raise last_exc if last_exc is not None else RuntimeError("Step execution failed.")

    async def _execute_single_step(
        self,
        step: WorkflowStep,
        ctx: dict[str, Any],
        *,
        run_id: str,
    ) -> str:
        if step.type == "knowledge_search":
            query = _render_template(step.query_template or "", ctx).strip()
            if not query:
                return "No query provided."
            hits = await self._knowledge.hybrid_search(
                query=query,
                top_k=step.top_k,
                min_score=step.min_score,
            )
            if not hits:
                return "No relevant documents found."
            return "\n\n".join(
                f"[{i}] ({hit.document_title}, score={hit.score})\n{hit.content}"
                for i, hit in enumerate(hits, start=1)
            )

        if step.type == "llm_step":
            prompt = _render_template(step.prompt_template or "", ctx).strip()
            messages: list[ChatMessage] = []
            if step.system_prompt:
                messages.append(ChatMessage(role="system", content=step.system_prompt))
            messages.append(ChatMessage(role="user", content=prompt))
            resp = await self._llm.generate(
                ModelRequest(messages=messages, temperature=step.temperature)
            )
            return resp.content

        if step.type == "tool_call":
            if not step.tool_name:
                raise ValueError("tool_call step missing tool_name.")
            args = _render_dict(step.arguments_template, ctx)
            record = await self._tools.execute(
                call_id=f"wf-{run_id}-{step.id}",
                tool_name=step.tool_name,
                raw_arguments=args,
                allow_mutating=step.allow_mutating,
            )
            if record.status in ("blocked", "error"):
                raise RuntimeError(record.output)
            return record.output

        raise ValueError(f"Unsupported step type: {step.type}")
