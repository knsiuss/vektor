import json
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.database import Base
from modules.conversations.repository import ConversationRepository
from modules.knowledge.repository import KnowledgeRepository
from modules.model_gateway.embeddings import LocalHashEmbeddingProvider
from modules.skills.registry import SkillRegistry
from modules.tools.builtins import build_default_tool_registry


async def test_session_memory_and_skills_tools(tmp_path: Path) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with factory() as session:
            conv_repo = ConversationRepository(session=session)
            conv = await conv_repo.create_conversation(title="Postgres Incident")
            await conv_repo.append_message(
                conversation=conv,
                role="assistant",
                content="We promoted replica pg-02 using pg_ctl promote.",
            )
            await session.commit()

            skills = SkillRegistry(tmp_path / "skills")
            know_repo = KnowledgeRepository(
                session=session,
                embedding_provider=LocalHashEmbeddingProvider(),
            )
            registry = build_default_tool_registry(
                conversation_repo=conv_repo,
                knowledge_repo=know_repo,
                skill_registry=skills,
            )

            # 1. Cross-session search
            search_res = await registry.execute(
                call_id="c1",
                tool_name="search_past_sessions",
                raw_arguments={"query": "pg_ctl promote"},
            )
            assert search_res.status == "success"
            hits = json.loads(search_res.output)
            assert len(hits) == 1
            assert hits[0]["title"] == "Postgres Incident"

            # 2. save_skill requires allow_mutating=True
            blocked = await registry.execute(
                call_id="c2",
                tool_name="save_skill",
                raw_arguments={
                    "name": "postgres-failover",
                    "description": "Failover steps",
                    "instructions": "Run pg_ctl promote.",
                },
                allow_mutating=False,
            )
            assert blocked.status == "blocked"

            saved = await registry.execute(
                call_id="c3",
                tool_name="save_skill",
                raw_arguments={
                    "name": "postgres-failover",
                    "description": "Failover steps",
                    "instructions": "Run pg_ctl promote.",
                },
                allow_mutating=True,
            )
            assert saved.status == "success"

            # 3. Progressive disclosure catalog + read_skill
            assert "postgres-failover" in skills.format_catalog_prompt()
            read_res = await registry.execute(
                call_id="c4",
                tool_name="read_skill",
                raw_arguments={"name": "postgres-failover"},
            )
            assert read_res.status == "success"
            assert "Run pg_ctl promote." in read_res.output
    finally:
        await engine.dispose()
