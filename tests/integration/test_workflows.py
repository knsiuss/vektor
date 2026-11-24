from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.database import Base
from modules.conversations.repository import ConversationRepository
from modules.identity.principal import Principal
from modules.knowledge.repository import KnowledgeRepository
from modules.model_gateway.embeddings import LocalHashEmbeddingProvider
from modules.model_gateway.schemas import ModelRequest, ModelResponse, StreamChunk, TokenUsage
from modules.tools.builtins import build_default_tool_registry
from modules.workflows.repository import WorkflowRepository
from modules.workflows.runner import WorkflowRunner
from modules.workflows.schemas import WorkflowCreateIn, WorkflowStep


class _MockLLM:
    @property
    def provider_name(self) -> str:
        return "mock-llm"

    async def generate(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(
            content=f"Triage summary based on: {request.messages[-1].content[:60]}",
            provider=self.provider_name,
            model="mock-model",
            usage=TokenUsage(prompt_tokens=10, completion_tokens=8, total_tokens=18),
            finish_reason="stop",
        )

    async def stream(self, request: ModelRequest) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(delta="ok", finish_reason="stop")


async def _make_session() -> tuple[Any, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def test_workflow_4_step_pause_approve_reject_and_tenant_isolation() -> None:
    engine, factory = await _make_session()
    tenant_a = Principal(user_id="alice", tenant_id="tenant-a", roles=frozenset({"admin"}))
    tenant_b = Principal(user_id="bob", tenant_id="tenant-b", roles=frozenset({"admin"}))

    try:
        async with factory() as session:
            embedder = LocalHashEmbeddingProvider()
            knowledge = KnowledgeRepository(session=session, embedding_provider=embedder)
            await knowledge.ingest_document(
                title="Failover.md",
                content="Run pg_ctl promote on the standby PostgreSQL node.",
                source="Failover.md",
            )
            tools = build_default_tool_registry(
                conversation_repo=ConversationRepository(session=session),
                knowledge_repo=knowledge,
            )

            repo_a = WorkflowRepository(session=session, principal=tenant_a)
            wf = await repo_a.create_workflow(
                WorkflowCreateIn(
                    name="Incident Triage",
                    steps=[
                        WorkflowStep(
                            id="s1",
                            type="knowledge_search",
                            name="Search SOP",
                            query_template="{{input.incident}}",
                            min_score=0.05,
                        ),
                        WorkflowStep(
                            id="s2",
                            type="llm_step",
                            name="Summarize",
                            prompt_template="Context: {{steps.s1.output}}",
                        ),
                        WorkflowStep(
                            id="s3",
                            type="human_approval",
                            name="Approve",
                            message_template="Approve: {{steps.s2.output}}",
                        ),
                        WorkflowStep(
                            id="s4",
                            type="tool_call",
                            name="Health Check",
                            tool_name="get_system_health",
                        ),
                    ],
                )
            )
            wf_row = await repo_a.get_workflow(wf.id)
            assert wf_row is not None

            runner_a = WorkflowRunner(
                session=session,
                principal=tenant_a,
                knowledge_repo=knowledge,
                llm_provider=_MockLLM(),
                tool_registry=tools,
            )

            # 1. Start run -> pauses at human_approval
            paused = await runner_a.start_run(wf_row, input_data={"incident": "pg_ctl promote"})
            assert paused.status == "waiting_approval"
            assert paused.current_step_index == 2
            assert len(paused.step_logs) == 3

            # 2. Tenant B cannot see Tenant A's workflow or run
            repo_b = WorkflowRepository(session=session, principal=tenant_b)
            assert await repo_b.get_workflow(wf.id) is None
            assert await repo_b.get_run(paused.id) is None

            # 3. Approve -> executes tool_call and completes
            found_run = await repo_a.get_run(paused.id)
            assert found_run is not None
            run_row, _ = found_run
            completed = await runner_a.resume_run(run_row, wf_row, decision="approve")
            assert completed.status == "completed"
            assert len(completed.step_logs) == 4
            assert completed.step_logs[-1].status == "completed"
            assert "healthy" in completed.step_logs[-1].output

            # 4. Reject stops run without running s4
            paused2 = await runner_a.start_run(wf_row, input_data={"incident": "pg_ctl promote"})
            found2 = await repo_a.get_run(paused2.id)
            assert found2 is not None
            rejected = await runner_a.resume_run(
                found2[0],
                wf_row,
                decision="reject",
                comment="Not needed",
            )
            assert rejected.status == "rejected"
            assert len(rejected.step_logs) == 3
    finally:
        await engine.dispose()
