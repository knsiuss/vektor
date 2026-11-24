import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.identity.principal import Principal
from modules.workflows.models import WorkflowDefinition, WorkflowRun
from modules.workflows.schemas import (
    WorkflowCreateIn,
    WorkflowOut,
    WorkflowRunOut,
    WorkflowStep,
    WorkflowStepLog,
)


class WorkflowRepository:
    """Tenant-scoped persistence for workflow definitions and execution runs."""

    def __init__(self, *, session: AsyncSession, principal: Principal) -> None:
        self._session = session
        self._principal = principal

    async def create_workflow(self, payload: WorkflowCreateIn) -> WorkflowOut:
        record = WorkflowDefinition(
            tenant_id=self._principal.tenant_id,
            owner_id=self._principal.user_id,
            name=payload.name.strip(),
            description=payload.description.strip(),
            trigger_type=payload.trigger_type,
            cron_expr=payload.cron_expr.strip() if payload.cron_expr else None,
            steps_json=json.dumps([step.model_dump(mode="json") for step in payload.steps]),
            enabled=payload.enabled,
        )
        self._session.add(record)
        await self._session.flush()
        return self._to_workflow_out(record)

    async def list_workflows(self, *, limit: int = 50) -> list[WorkflowOut]:
        stmt = (
            select(WorkflowDefinition)
            .where(WorkflowDefinition.tenant_id == self._principal.tenant_id)
            .order_by(WorkflowDefinition.created_at.desc())
            .limit(limit)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [self._to_workflow_out(row) for row in rows]

    async def get_workflow(self, workflow_id: str) -> WorkflowDefinition | None:
        stmt = select(WorkflowDefinition).where(
            WorkflowDefinition.id == workflow_id,
            WorkflowDefinition.tenant_id == self._principal.tenant_id,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def delete_workflow(self, workflow_id: str) -> bool:
        record = await self.get_workflow(workflow_id)
        if record is None:
            return False
        await self._session.delete(record)
        await self._session.flush()
        return True

    async def get_run(self, run_id: str) -> tuple[WorkflowRun, str] | None:
        stmt = (
            select(WorkflowRun, WorkflowDefinition.name)
            .join(WorkflowDefinition, WorkflowDefinition.id == WorkflowRun.workflow_id)
            .where(
                WorkflowRun.id == run_id,
                WorkflowRun.tenant_id == self._principal.tenant_id,
            )
        )
        row = (await self._session.execute(stmt)).first()
        if row is None:
            return None
        return row[0], str(row[1])

    async def list_runs(self, *, limit: int = 50) -> list[WorkflowRunOut]:
        stmt = (
            select(WorkflowRun, WorkflowDefinition.name)
            .join(WorkflowDefinition, WorkflowDefinition.id == WorkflowRun.workflow_id)
            .where(WorkflowRun.tenant_id == self._principal.tenant_id)
            .order_by(WorkflowRun.started_at.desc())
            .limit(limit)
        )
        rows = (await self._session.execute(stmt)).all()
        return [self.to_run_out(run, str(wf_name)) for run, wf_name in rows]

    @staticmethod
    def _to_workflow_out(record: WorkflowDefinition) -> WorkflowOut:
        raw_steps = json.loads(record.steps_json)
        steps = [WorkflowStep.model_validate(item) for item in raw_steps]
        return WorkflowOut(
            id=record.id,
            name=record.name,
            description=record.description,
            trigger_type=record.trigger_type,
            cron_expr=record.cron_expr,
            steps=steps,
            enabled=record.enabled,
            owner_id=record.owner_id,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def to_run_out(run: WorkflowRun, workflow_name: str) -> WorkflowRunOut:
        raw_input: dict[str, Any] = json.loads(run.input_json) if run.input_json else {}
        raw_logs = json.loads(run.step_logs_json) if run.step_logs_json else []
        logs = [WorkflowStepLog.model_validate(item) for item in raw_logs]
        return WorkflowRunOut(
            id=run.id,
            workflow_id=run.workflow_id,
            workflow_name=workflow_name,
            status=run.status,
            current_step_index=run.current_step_index,
            triggered_by=run.triggered_by,
            input=raw_input,
            step_logs=logs,
            error_message=run.error_message,
            started_at=run.started_at,
            finished_at=run.finished_at,
        )
