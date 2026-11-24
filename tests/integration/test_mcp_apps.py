from pathlib import Path

import httpx

from api.main import create_app
from core.config.settings import Settings
from modules.mcp_apps.registry import MCP_APP_MIME_TYPE
from modules.mcp_apps.widgets import OPS_HEALTH_WIDGET_URI


async def test_mcp_apps_resource_and_tool_bridge(tmp_path: Path) -> None:
    db_file = tmp_path / "mcp_apps.db"
    settings = Settings(
        _env_file=None,
        app_env="development",
        database_url=f"sqlite+aiosqlite:///{db_file.as_posix()}",
        llm_embedding_model="local",
    )
    app = create_app(settings)

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Read registered UI resource
            res = await client.get(
                "/api/v1/mcp/resources",
                params={"uri": OPS_HEALTH_WIDGET_URI},
            )
            assert res.status_code == 200
            assert "max-age=300" in res.headers.get("cache-control", "")
            payload = res.json()
            assert payload["uri"] == OPS_HEALTH_WIDGET_URI
            assert payload["mime_type"] == MCP_APP_MIME_TYPE
            assert "ui/initialize" in payload["html"]

            # 2. Missing resource returns 404
            missing = await client.get(
                "/api/v1/mcp/resources",
                params={"uri": "ui://widget/does-not-exist.html"},
            )
            assert missing.status_code == 404

            # 3. Render tool returns ui_resource_uri; data tool does not
            render_call = await client.post(
                "/api/v1/mcp/tools/call",
                json={"name": "render_ops_health_widget", "arguments": {}},
            )
            assert render_call.status_code == 200
            render_data = render_call.json()
            assert render_data["status"] == "success"
            assert render_data["ui_resource_uri"] == OPS_HEALTH_WIDGET_URI

            data_call = await client.post(
                "/api/v1/mcp/tools/call",
                json={"name": "get_system_health", "arguments": {}},
            )
            assert data_call.status_code == 200
            assert data_call.json()["ui_resource_uri"] is None

            # 4. Unknown tool is blocked by allowlist
            blocked = await client.post(
                "/api/v1/mcp/tools/call",
                json={"name": "drop_database", "arguments": {}},
            )
            assert blocked.status_code == 200
            assert blocked.json()["status"] == "blocked"
