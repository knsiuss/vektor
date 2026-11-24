from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from api.dependencies import get_embedding_provider
from api.main import create_app
from core.config.settings import Settings
from modules.identity.principal import hash_api_key
from modules.identity.repository import ApiKeyRepository


class _CountingEmbeddings:
    """Deterministic vectors plus a call counter so re-indexing can be proven."""

    embedding_model = "fake-embed"

    def __init__(self) -> None:
        self.batches: list[int] = []

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.batches.append(len(texts))
        return [[float(len(text)), 1.0] for text in texts]


def _h(key: str) -> dict[str, str]:
    return {"X-API-Key": key}


async def _make_key(app: FastAPI, *, tenant: str, user: str, roles: str = "member") -> str:
    raw = f"vk_fresh_{tenant}_{user}"
    async with app.state.session_factory() as session:
        await ApiKeyRepository(session).create(
            tenant_id=tenant,
            user_id=user,
            key_hash=hash_api_key(raw),
            roles=roles,
            label=None,
            expires_at=None,
        )
        await session.commit()
    return raw


@asynccontextmanager
async def _app() -> AsyncIterator[tuple[httpx.AsyncClient, _CountingEmbeddings, dict[str, str]]]:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url="sqlite+aiosqlite:///:memory:",
    )
    app = create_app(settings=settings)
    embeddings = _CountingEmbeddings()
    app.dependency_overrides[get_embedding_provider] = lambda: embeddings

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client,
    ):
        yield client, embeddings, {
            "alice": await _make_key(app, tenant="acme", user="alice"),
            "bob": await _make_key(app, tenant="acme", user="bob"),
            "carol": await _make_key(app, tenant="acme", user="carol", roles="admin"),
        }


async def _ingest(
    client: httpx.AsyncClient,
    key: str,
    *,
    title: str = "Runbook",
    content: str = "promote the replica with pg_ctl",
    visibility: str = "private",
    source_url: str | None = None,
) -> dict:
    body: dict = {"title": title, "content": content, "visibility": visibility}
    if source_url is not None:
        body["source_url"] = source_url
    response = await client.post("/api/v1/knowledge/documents", json=body, headers=_h(key))
    assert response.status_code == 201, response.text
    return response.json()


async def test_ingest_records_sync_time_and_source_url() -> None:
    """Verify a new document is fresh and keeps the URL it came from."""
    async with _app() as (client, _embeddings, keys):
        document = await _ingest(
            client,
            keys["alice"],
            source_url="https://wiki.example.com/runbooks/failover",
        )
        listed = await client.get("/api/v1/knowledge/documents", headers=_h(keys["alice"]))

    assert document["source_url"] == "https://wiki.example.com/runbooks/failover"
    assert document["last_synced_at"] is not None
    assert document["is_stale"] is False
    row = [item for item in listed.json() if item["id"] == document["id"]][0]
    assert row["is_stale"] is False


async def test_owner_can_reindex_and_embeddings_are_recomputed() -> None:
    """Verify re-indexing re-embeds the stored chunks and refreshes the timestamp."""
    async with _app() as (client, embeddings, keys):
        document = await _ingest(client, keys["alice"])
        batches_after_ingest = len(embeddings.batches)

        reindexed = await client.post(
            f"/api/v1/knowledge/documents/{document['id']}/reindex",
            headers=_h(keys["alice"]),
        )

    assert reindexed.status_code == 200
    assert len(embeddings.batches) == batches_after_ingest + 1
    assert reindexed.json()["chunk_count"] == document["chunk_count"]
    assert reindexed.json()["last_synced_at"] is not None


async def test_reindex_of_a_private_document_is_hidden_from_others() -> None:
    """Verify a document you cannot read is reported as missing, not forbidden."""
    async with _app() as (client, _embeddings, keys):
        document = await _ingest(client, keys["alice"])

        response = await client.post(
            f"/api/v1/knowledge/documents/{document['id']}/reindex",
            headers=_h(keys["bob"]),
        )

    assert response.status_code == 404


async def test_reader_who_cannot_manage_gets_403_but_admin_can_reindex() -> None:
    """Verify tenant-visible documents are readable by members but only managed by admins."""
    async with _app() as (client, _embeddings, keys):
        document = await _ingest(client, keys["alice"], visibility="tenant")

        blocked = await client.post(
            f"/api/v1/knowledge/documents/{document['id']}/reindex",
            headers=_h(keys["bob"]),
        )
        allowed = await client.post(
            f"/api/v1/knowledge/documents/{document['id']}/reindex",
            headers=_h(keys["carol"]),
        )

    assert blocked.status_code == 403
    assert allowed.status_code == 200
