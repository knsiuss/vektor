from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_chat_service, get_db_session, get_principal
from api.main import create_app
from core.config.settings import Settings
from modules.ai_runtime.service import ChatService
from modules.conversations.repository import ConversationRepository
from modules.identity.principal import Principal, hash_api_key
from modules.identity.repository import ApiKeyRepository
from modules.model_gateway.schemas import ModelRequest, ModelResponse, TokenUsage


class _FakeProvider:
    @property
    def provider_name(self) -> str:
        return "fake-provider"

    async def generate(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(
            content="ok",
            provider=self.provider_name,
            model="fake-model",
            usage=TokenUsage(prompt_tokens=3, completion_tokens=2, total_tokens=5),
            finish_reason="stop",
        )


def _h(key: str) -> dict[str, str]:
    return {"X-API-Key": key}


async def _make_key(
    app: FastAPI,
    *,
    tenant: str,
    user: str,
    roles: str = "member",
    revoked: bool = False,
    expired: bool = False,
) -> str:
    raw = f"vk_test_{tenant}_{user}"
    async with app.state.session_factory() as session:
        row = await ApiKeyRepository(session).create(
            tenant_id=tenant,
            user_id=user,
            key_hash=hash_api_key(raw),
            roles=roles,
            label=None,
            expires_at=datetime.now(UTC) - timedelta(days=1) if expired else None,
        )
        if revoked:
            row.revoked_at = datetime.now(UTC)
        await session.commit()
    return raw


@asynccontextmanager
async def _app(
    settings: Settings | None = None,
) -> AsyncIterator[tuple[httpx.AsyncClient, FastAPI]]:
    resolved = settings or Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url="sqlite+aiosqlite:///:memory:",
    )
    app = create_app(settings=resolved)

    def _override_chat_service(
        session: Annotated[AsyncSession, Depends(get_db_session)],
        principal: Annotated[Principal, Depends(get_principal)],
    ) -> ChatService:
        return ChatService(
            provider=_FakeProvider(),
            repository=ConversationRepository(session=session, principal=principal),
        )

    app.dependency_overrides[get_chat_service] = _override_chat_service

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client,
    ):
        yield client, app


async def _seed(app: FastAPI) -> dict[str, str]:
    return {
        "alice": await _make_key(app, tenant="acme", user="alice"),
        "bob": await _make_key(app, tenant="acme", user="bob"),
        "carol": await _make_key(app, tenant="acme", user="carol", roles="admin"),
        "dave": await _make_key(app, tenant="globex", user="dave", roles="admin"),
    }


async def _alice_creates_conversation(client: httpx.AsyncClient, keys: dict[str, str]) -> str:
    response = await client.post(
        "/api/v1/chat", json={"message": "alice private note"}, headers=_h(keys["alice"])
    )
    assert response.status_code == 200
    return str(response.json()["conversation_id"])


async def test_member_cannot_see_or_change_another_users_conversation() -> None:
    """Verify a same-tenant member gets 404 for read, delete and chat on someone else's thread."""
    async with _app() as (client, app):
        keys = await _seed(app)
        cid = await _alice_creates_conversation(client, keys)

        own = await client.get(f"/api/v1/conversations/{cid}", headers=_h(keys["alice"]))
        read = await client.get(f"/api/v1/conversations/{cid}", headers=_h(keys["bob"]))
        delete = await client.delete(f"/api/v1/conversations/{cid}", headers=_h(keys["bob"]))
        continued = await client.post(
            "/api/v1/chat",
            json={"conversation_id": cid, "message": "hijack"},
            headers=_h(keys["bob"]),
        )
        bob_list = await client.get("/api/v1/conversations", headers=_h(keys["bob"]))
        still_there = await client.get(f"/api/v1/conversations/{cid}", headers=_h(keys["alice"]))

    assert own.status_code == 200
    assert read.status_code == 404
    assert delete.status_code == 404
    assert continued.status_code == 404
    assert bob_list.json() == []
    assert still_there.status_code == 200


async def test_admin_of_another_tenant_cannot_see_the_conversation() -> None:
    """Verify tenant isolation holds even against administrators of a different tenant."""
    async with _app() as (client, app):
        keys = await _seed(app)
        cid = await _alice_creates_conversation(client, keys)

        read = await client.get(f"/api/v1/conversations/{cid}", headers=_h(keys["dave"]))
        delete = await client.delete(f"/api/v1/conversations/{cid}", headers=_h(keys["dave"]))
        tenant_list = await client.get("/api/v1/admin/conversations", headers=_h(keys["dave"]))

    assert read.status_code == 404
    assert delete.status_code == 404
    assert tenant_list.status_code == 200
    assert tenant_list.json() == []


async def test_tenant_admin_read_is_allowed_and_audited() -> None:
    """Verify an admin can open a colleague's thread and that the access is logged."""
    async with _app() as (client, app):
        keys = await _seed(app)
        cid = await _alice_creates_conversation(client, keys)

        # The owner reading her own thread must not create an audit record.
        await client.get(f"/api/v1/conversations/{cid}", headers=_h(keys["alice"]))
        before = await client.get("/api/v1/admin/audit-log", headers=_h(keys["carol"]))

        admin_read = await client.get(f"/api/v1/conversations/{cid}", headers=_h(keys["carol"]))
        after = await client.get("/api/v1/admin/audit-log", headers=_h(keys["carol"]))
        other_tenant_log = await client.get("/api/v1/admin/audit-log", headers=_h(keys["dave"]))

    assert admin_read.status_code == 200
    assert admin_read.json()["id"] == cid
    assert before.json() == []

    entries = [e for e in after.json() if e["action"] == "conversation.read"]
    assert len(entries) == 1
    assert entries[0]["actor_id"] == "carol"
    assert entries[0]["resource_id"] == cid
    assert entries[0]["resource_owner_id"] == "alice"
    assert entries[0]["tenant_id"] == "acme"
    assert other_tenant_log.json() == []


async def test_admin_listing_and_delete_are_audited() -> None:
    """Verify tenant-wide listing and cross-user deletion both leave audit records."""
    async with _app() as (client, app):
        keys = await _seed(app)
        cid = await _alice_creates_conversation(client, keys)

        listing = await client.get("/api/v1/admin/conversations", headers=_h(keys["carol"]))
        deleted = await client.delete(f"/api/v1/conversations/{cid}", headers=_h(keys["carol"]))
        gone = await client.get(f"/api/v1/conversations/{cid}", headers=_h(keys["alice"]))
        log = await client.get("/api/v1/admin/audit-log", headers=_h(keys["carol"]))

    assert [item["id"] for item in listing.json()] == [cid]
    assert listing.json()[0]["owner_id"] == "alice"
    assert deleted.status_code == 204
    assert gone.status_code == 404
    actions = {entry["action"] for entry in log.json()}
    assert {"conversation.list", "conversation.delete"} <= actions


async def test_member_is_forbidden_from_admin_endpoints() -> None:
    """Verify admin endpoints return 403 for non-admin principals."""
    async with _app() as (client, app):
        keys = await _seed(app)
        responses = [
            await client.get("/api/v1/admin/conversations", headers=_h(keys["bob"])),
            await client.get("/api/v1/admin/usage", headers=_h(keys["bob"])),
            await client.get("/api/v1/admin/audit-log", headers=_h(keys["bob"])),
        ]

    assert [r.status_code for r in responses] == [403, 403, 403]


async def test_usage_is_per_user_and_admin_usage_is_tenant_wide() -> None:
    """Verify /usage counts only the caller's data while /admin/usage covers the tenant."""
    async with _app() as (client, app):
        keys = await _seed(app)
        await _alice_creates_conversation(client, keys)

        alice = await client.get("/api/v1/usage", headers=_h(keys["alice"]))
        bob = await client.get("/api/v1/usage", headers=_h(keys["bob"]))
        carol_self = await client.get("/api/v1/usage", headers=_h(keys["carol"]))
        carol_tenant = await client.get("/api/v1/admin/usage", headers=_h(keys["carol"]))
        dave_tenant = await client.get("/api/v1/admin/usage", headers=_h(keys["dave"]))

    assert alice.json()["total_conversations"] == 1
    assert alice.json()["total_tokens"] == 5
    assert bob.json()["total_conversations"] == 0
    assert carol_self.json()["total_conversations"] == 0
    assert carol_tenant.json()["total_conversations"] == 1
    assert carol_tenant.json()["total_tokens"] == 5
    assert dave_tenant.json()["total_conversations"] == 0


async def test_revoked_and_expired_keys_are_rejected_and_legacy_key_still_works() -> None:
    """Verify revoked/expired DB keys give 401, while a legacy shared key maps to a member."""
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url="sqlite+aiosqlite:///:memory:",
        app_env="staging",
        api_keys="vk-legacy-shared",
    )
    async with _app(settings) as (client, app):
        good = await _make_key(app, tenant="acme", user="alice")
        revoked = await _make_key(app, tenant="acme", user="rev", revoked=True)
        expired = await _make_key(app, tenant="acme", user="exp", expired=True)

        ok = await client.get("/api/v1/conversations", headers=_h(good))
        no_revoked = await client.get("/api/v1/conversations", headers=_h(revoked))
        no_expired = await client.get("/api/v1/conversations", headers=_h(expired))
        unknown = await client.get("/api/v1/conversations", headers=_h("vk-nope"))
        legacy = await client.get("/api/v1/conversations", headers=_h("vk-legacy-shared"))
        legacy_admin = await client.get("/api/v1/admin/usage", headers=_h("vk-legacy-shared"))

    assert ok.status_code == 200
    assert no_revoked.status_code == 401
    assert no_expired.status_code == 401
    assert unknown.status_code == 401
    assert legacy.status_code == 200
    assert legacy_admin.status_code == 403
