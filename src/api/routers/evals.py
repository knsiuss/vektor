from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_chat_service, get_db_session, get_principal
from modules.ai_runtime.schemas import ChatTurnInput
from modules.ai_runtime.service import ChatService
from modules.evals.models import EvalCase
from modules.evals.runner import evaluate_reply, summarize_eval_results
from modules.identity.principal import Principal

router = APIRouter(prefix="/api/v1/evals", tags=["evals"])


class EvalCaseCreate(BaseModel):
    bot_id: str | None = None
    question: str = Field(min_length=1, max_length=2000)
    expected_facts: list[str] = Field(default_factory=list, max_length=20)
    forbidden_claims: list[str] = Field(default_factory=list, max_length=20)


class EvalCaseOut(BaseModel):
    id: str
    bot_id: str | None
    question: str
    expected_facts: list[str]
    forbidden_claims: list[str]
    created_at: datetime


class EvalRunIn(BaseModel):
    bot_id: str | None = None
    document_ids: list[str] | None = None


class EvalCaseResultOut(BaseModel):
    case_id: str
    question: str
    passed: bool
    missing_facts: list[str]
    triggered_forbidden: list[str]
    reply: str


class EvalRunOut(BaseModel):
    total: int
    passed: int
    pass_rate: float
    results: list[EvalCaseResultOut]


@router.post("/cases", response_model=EvalCaseOut, status_code=status.HTTP_201_CREATED)
async def create_eval_case(
    payload: EvalCaseCreate,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> EvalCaseOut:
    row = EvalCase(
        tenant_id=principal.tenant_id,
        bot_id=payload.bot_id,
        question=payload.question,
        expected_facts=payload.expected_facts,
        forbidden_claims=payload.forbidden_claims,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return EvalCaseOut(
        id=row.id,
        bot_id=row.bot_id,
        question=row.question,
        expected_facts=row.expected_facts,
        forbidden_claims=row.forbidden_claims,
        created_at=row.created_at,
    )


@router.get("/cases", response_model=list[EvalCaseOut])
async def list_eval_cases(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> list[EvalCaseOut]:
    stmt = (
        select(EvalCase)
        .where(EvalCase.tenant_id == principal.tenant_id)
        .order_by(EvalCase.created_at.desc())
    )
    rows = list((await session.execute(stmt)).scalars().all())
    return [
        EvalCaseOut(
            id=r.id,
            bot_id=r.bot_id,
            question=r.question,
            expected_facts=r.expected_facts,
            forbidden_claims=r.forbidden_claims,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.delete("/cases/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_eval_case(
    case_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> None:
    stmt = select(EvalCase).where(
        EvalCase.id == case_id, EvalCase.tenant_id == principal.tenant_id
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Eval case not found.")
    await session.delete(row)
    await session.flush()


@router.post("/run", response_model=EvalRunOut)
async def run_eval_suite(
    payload: EvalRunIn,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    principal: Annotated[Principal, Depends(get_principal)],
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
) -> EvalRunOut:
    stmt = select(EvalCase).where(EvalCase.tenant_id == principal.tenant_id)
    if payload.bot_id:
        stmt = stmt.where(EvalCase.bot_id == payload.bot_id)
    cases = list((await session.execute(stmt)).scalars().all())

    results = []
    for case in cases:
        turn = await chat_service.execute_turn(
            ChatTurnInput(
                message=case.question,
                document_ids=payload.document_ids,
                enable_tools=False,
                allow_mutating_tools=False,
            )
        )
        results.append(
            evaluate_reply(
                case_id=case.id,
                question=case.question,
                reply=turn.reply,
                expected_facts=case.expected_facts,
                forbidden_claims=case.forbidden_claims,
            )
        )

    summary = summarize_eval_results(results)
    return EvalRunOut(
        total=summary.total,
        passed=summary.passed,
        pass_rate=summary.pass_rate,
        results=[
            EvalCaseResultOut(
                case_id=r.case_id,
                question=r.question,
                passed=r.passed,
                missing_facts=r.missing_facts,
                triggered_forbidden=r.triggered_forbidden,
                reply=r.reply,
            )
            for r in summary.results
        ],
    )
