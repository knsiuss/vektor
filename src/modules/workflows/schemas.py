from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

WorkflowStepType = Literal["knowledge_search", "llm_step", "tool_call", "human_approval"]
WorkflowRunStatus = Literal[
    "pending",
    "running",
    "waiting_approval",
    "completed",
    "failed",
    "rejected",
]


class WorkflowStep(BaseModel):
    """Single step definition inside a workflow."""

    id: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    type: WorkflowStepType
    name: str = Field(..., min_length=1, max_length=120)
    max_retries: int = Field(default=0, ge=0, le=2)

    # knowledge_search
    query_template: str | None = None
    top_k: int = Field(default=4, ge=1, le=10)
    min_score: float = Field(default=0.15, ge=0.0, le=1.0)

    # llm_step
    system_prompt: str | None = None
    prompt_template: str | None = None
    temperature: float = Field(default=0.1, ge=0.0, le=1.0)

    # tool_call
    tool_name: str | None = None
    arguments_template: dict[str, Any] = Field(default_factory=dict)
    allow_mutating: bool = False

    # human_approval
    message_template: str | None = None


class WorkflowCreateIn(BaseModel):
    """Request payload to create a workflow."""

    name: str = Field(..., min_length=1, max_length=160)
    description: str = Field(default="", max_length=1000)
    trigger_type: Literal["manual", "webhook", "cron"] = "manual"
    cron_expr: str | None = Field(default=None, max_length=64)
    steps: list[WorkflowStep] = Field(..., min_length=1, max_length=25)
    enabled: bool = True


class WorkflowOut(BaseModel):
    """Client-facing representation of a workflow definition."""

    id: str
    name: str
    description: str
    trigger_type: str
    cron_expr: str | None = None
    steps: list[WorkflowStep]
    enabled: bool
    owner_id: str
    created_at: datetime
    updated_at: datetime


class WorkflowRunStartIn(BaseModel):
    """Request payload to start a workflow run."""

    input: dict[str, Any] = Field(default_factory=dict)


class WorkflowApprovalIn(BaseModel):
    """Decision payload for a paused human_approval step."""

    decision: Literal["approve", "reject"]
    comment: str | None = Field(default=None, max_length=500)


class WorkflowStepLog(BaseModel):
    """Execution record for one step in a workflow run."""

    step_id: str
    step_name: str
    step_type: WorkflowStepType
    status: Literal["completed", "waiting_approval", "approved", "rejected", "failed"]
    output: str = ""
    error: str | None = None
    started_at: datetime
    finished_at: datetime | None = None


class WorkflowRunOut(BaseModel):
    """Client-facing representation of a workflow run and its step logs."""

    id: str
    workflow_id: str
    workflow_name: str
    status: str
    current_step_index: int
    triggered_by: str
    input: dict[str, Any]
    step_logs: list[WorkflowStepLog]
    error_message: str | None = None
    started_at: datetime
    finished_at: datetime | None = None
