import json
from datetime import UTC, datetime
from typing import Any

from modules.conversations.repository import ConversationRepository
from modules.knowledge.repository import KnowledgeRepository
from modules.tools.registry import ToolRegistry
from modules.tools.schemas import ToolDefinition


def build_default_tool_registry(
    *,
    conversation_repo: ConversationRepository,
    knowledge_repo: KnowledgeRepository,
) -> ToolRegistry:
    """Populate a ToolRegistry with built-in read-only AI Operations diagnostics tools."""
    registry = ToolRegistry()

    async def _system_health(_args: dict[str, Any]) -> str:
        return json.dumps(
            {
                "status": "healthy",
                "service": "Vektor AI Operations",
                "timestamp_utc": datetime.now(UTC).isoformat(),
            }
        )

    registry.register(
        ToolDefinition(
            name="get_system_health",
            description="Check Vektor service liveness and current UTC server timestamp.",
            parameters_schema={"type": "object", "properties": {}, "required": []},
            risk_level="read",
        ),
        _system_health,
    )

    async def _usage_report(_args: dict[str, Any]) -> str:
        summary = await conversation_repo.get_usage_summary()
        return summary.model_dump_json()

    registry.register(
        ToolDefinition(
            name="get_token_usage_report",
            description="Retrieve aggregated conversation counts and token usage across models.",
            parameters_schema={"type": "object", "properties": {}, "required": []},
            risk_level="read",
        ),
        _usage_report,
    )

    async def _search_kb(args: dict[str, Any]) -> str:
        query = str(args.get("query", "")).strip()
        if not query:
            return "Error: 'query' parameter is required."
        top_k = min(max(int(args.get("top_k", 3)), 1), 10)
        hits = await knowledge_repo.hybrid_search(query=query, top_k=top_k, min_score=0.2)
        if not hits:
            return "No matching documents found in the knowledge base."
        return json.dumps([hit.model_dump() for hit in hits])

    registry.register(
        ToolDefinition(
            name="search_knowledge_base",
            description="Query Vektor's hybrid vector knowledge base for runbooks, SOPs, or docs.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Technical search query"},
                    "top_k": {"type": "integer", "description": "Max chunks to return (1-10)"},
                },
                "required": ["query"],
            },
            risk_level="read",
        ),
        _search_kb,
    )

    return registry
