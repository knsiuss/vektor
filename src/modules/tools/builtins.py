import json
from datetime import UTC, datetime
from typing import Any

from core.config.settings import get_settings
from modules.conversations.repository import ConversationRepository
from modules.knowledge.repository import KnowledgeRepository
from modules.mcp_apps.widgets import OPS_HEALTH_WIDGET_URI
from modules.sandbox.backend import SandboxBackend, build_sandbox_backend
from modules.skills.registry import SkillRegistry
from modules.tools.registry import ToolRegistry
from modules.tools.schemas import ToolDefinition


def build_default_tool_registry(
    *,
    conversation_repo: ConversationRepository,
    knowledge_repo: KnowledgeRepository,
    skill_registry: SkillRegistry | None = None,
    sandbox_backend: SandboxBackend | None = None,
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

    registry.register(
        ToolDefinition(
            name="render_ops_health_widget",
            description=(
                "Render an interactive system health dashboard widget in the chat UI "
                "when the user asks to view or monitor service health visually."
            ),
            parameters_schema={"type": "object", "properties": {}, "required": []},
            risk_level="read",
            ui_resource_uri=OPS_HEALTH_WIDGET_URI,
        ),
        _system_health,
    )

    async def _search_sessions(args: dict[str, Any]) -> str:
        query = str(args.get("query", "")).strip()
        if not query:
            return "Error: 'query' parameter is required."
        limit = min(max(int(args.get("limit", 5)), 1), 10)
        hits = await conversation_repo.search_messages(query=query, limit=limit)
        if not hits:
            return "No matching past conversation messages found."
        return json.dumps(hits)

    registry.register(
        ToolDefinition(
            name="search_past_sessions",
            description=(
                "Search past conversation messages across sessions for prior decisions "
                "or context."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "limit": {"type": "integer", "description": "Max matches (1-10)"},
                },
                "required": ["query"],
            },
            risk_level="read",
        ),
        _search_sessions,
    )

    settings = get_settings()
    skills = skill_registry or SkillRegistry(settings.skills_dir)
    sandbox = sandbox_backend or build_sandbox_backend(settings)

    async def _read_skill(args: dict[str, Any]) -> str:
        name = str(args.get("name", "")).strip()
        if not name:
            return "Error: 'name' parameter is required."
        content = skills.read_skill(name)
        return content if content is not None else f"Skill '{name}' not found."

    registry.register(
        ToolDefinition(
            name="read_skill",
            description="Load full instructions from an agentskills.io SKILL.md by name.",
            parameters_schema={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
            risk_level="read",
        ),
        _read_skill,
    )

    async def _save_skill(args: dict[str, Any]) -> str:
        name = str(args.get("name", "")).strip()
        description = str(args.get("description", "")).strip()
        instructions = str(args.get("instructions", "")).strip()
        if not name or not instructions:
            return "Error: 'name' and 'instructions' are required."
        path = skills.save_skill(
            name=name,
            description=description or "Learned operational skill.",
            instructions=instructions,
        )
        return json.dumps({"saved": str(path), "name": name})

    registry.register(
        ToolDefinition(
            name="save_skill",
            description="Save a reusable operational procedure as an agentskills.io SKILL.md file.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "instructions": {"type": "string"},
                },
                "required": ["name", "instructions"],
            },
            risk_level="mutating",
        ),
        _save_skill,
    )

    async def _run_sandbox(args: dict[str, Any]) -> str:
        command = str(args.get("command", "")).strip()
        if not command:
            return "Error: 'command' parameter is required."
        timeout = min(max(float(args.get("timeout_seconds", 15.0)), 1.0), 60.0)
        res = await sandbox.run(command, timeout_seconds=timeout)
        return json.dumps(
            {
                "exit_code": res.exit_code,
                "stdout": res.stdout,
                "stderr": res.stderr,
                "timed_out": res.timed_out,
            }
        )

    registry.register(
        ToolDefinition(
            name="run_sandbox_command",
            description="Execute a shell command inside the isolated Docker/SSH sandbox backend.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "timeout_seconds": {"type": "number"},
                },
                "required": ["command"],
            },
            risk_level="mutating",
        ),
        _run_sandbox,
    )

    return registry
