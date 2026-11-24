import hashlib
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from api.dependencies import get_embedding_provider
from api.main import create_app
from core.config.settings import Settings
from modules.identity.principal import hash_api_key
from modules.identity.repository import ApiKeyRepository

_DIM = 32


class _BagOfWordsEmbeddings:
    """Deterministic embeddings so search ranking works without a real provider."""

    embedding_model = "fake-bow"

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            vec = [0.0] * _DIM
            for token in re.findall(r"[a-z0-9]+", text.lower()):
                slot = int(hashlib.md5(token.encode()).hexdigest(), 16) % _DIM  # noqa: S324
                vec[slot] += 1.0
            vectors.append(vec)
        return vectors


def _h(key: str) -> dict[str, str]:
    return {"X-API-Key": key}


async def _make_key(app: FastAPI, *, tenant: str, user: str, roles: str = "member") -> str:
    raw = f"vk_kb_{tenant}_{user}"
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
async def _app() -> AsyncIterator[tuple[httpx.AsyncClient, dict[str, str]]]:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url="sqlite+aiosqlite:///:memory:",
    )
    app = create_app(settings=settings)
    app.dependency_overrides[get_embedding_provider] = lambda: _BagOfWordsEmbeddings()

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client,
    ):
        keys = {
            "alice": await _make_key(app, tenant="acme", user="alice"),
            "bob": await _make_key(app, tenant="acme", user="bob"),
            "carol": await _make_key(app, tenant="acme", user="carol", roles="admin"),
            "dave": await _make_key(app, tenant="globex", user="dave", roles="admin"),
        }
        yield client, keys


async def _ingest(
    client: httpx.AsyncClient,
    key: str,
    *,
    title: str,
    content: str,
    visibility: str = "private",
) -> str:
    response = await client.post(
        "/api/v1/knowledge/documents",
        json={"title": title, "content": content, "visibility": visibility},
        headers=_h(key),
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def _titles_in_search(client: httpx.AsyncClient, key: str, query: str) -> set[str]:
    response = await client.post(
        "/api/v1/knowledge/search",
        json={"query": query, "min_score": 0.0, "top_k": 20},
        headers=_h(key),
    )
    assert response.status_code == 200
    return {item["document_title"] for item in response.json()}


async def _listed_ids(client: httpx.AsyncClient, key: str) -> set[str]:
    response = await client.get("/api/v1/knowledge/documents", headers=_h(key))
    assert response.status_code == 200
    return {item["id"] for item in response.json()}


async def test_private_document_is_visible_only_to_its_owner() -> None:
    """Verify private docs never appear in list, search or delete for other users."""
    async with _app() as (client, keys):
        doc = await _ingest(client, keys["alice"], title="Alice notes", content="alpha secret plan")

        alice_list = await _listed_ids(client, keys["alice"])
        bob_list = await _listed_ids(client, keys["bob"])
        alice_hits = await _titles_in_search(client, keys["alice"], "alpha secret")
        bob_hits = await _titles_in_search(client, keys["bob"], "alpha secret")
        bob_delete = await client.delete(
            f"/api/v1/knowledge/documents/{doc}", headers=_h(keys["bob"])
        )
        carol_hits = await _titles_in_search(client, keys["carol"], "alpha secret")

    assert alice_list == {doc}
    assert bob_list == set()
    assert alice_hits == {"Alice notes"}
    assert bob_hits == set()
    assert bob_delete.status_code == 404
    # Admins can manage documents but do not gain read access to private content.
    assert carol_hits == set()


async def test_other_tenant_never_sees_documents_even_tenant_visible_ones() -> None:
    """Verify tenant isolation holds for documents marked visible to the whole tenant."""
    async with _app() as (client, keys):
        doc = await _ingest(
            client, keys["alice"], title="Acme handbook", content="beta onboarding guide",
            visibility="tenant",
        )
        bob_hits = await _titles_in_search(client, keys["bob"], "beta onboarding")
        dave_hits = await _titles_in_search(client, keys["dave"], "beta onboarding")
        dave_list = await _listed_ids(client, keys["dave"])
        dave_delete = await client.delete(
            f"/api/v1/knowledge/documents/{doc}", headers=_h(keys["dave"])
        )
        dave_patch = await client.patch(
            f"/api/v1/knowledge/documents/{doc}/visibility",
            json={"visibility": "private"},
            headers=_h(keys["dave"]),
        )

    assert bob_hits == {"Acme handbook"}
    assert dave_hits == set()
    assert dave_list == set()
    assert dave_delete.status_code == 404
    assert dave_patch.status_code == 404


async def test_tenant_visible_document_member_cannot_modify_but_admin_can_with_audit() -> None:
    """Verify readable-but-foreign docs give 403 to members and audited deletes to admins."""
    async with _app() as (client, keys):
        doc = await _ingest(
            client, keys["alice"], title="Shared runbook", content="gamma restart steps",
            visibility="tenant",
        )
        bob_delete = await client.delete(
            f"/api/v1/knowledge/documents/{doc}", headers=_h(keys["bob"])
        )
        bob_grant = await client.post(
            f"/api/v1/knowledge/documents/{doc}/grants",
            json={"grantee_id": "bob"},
            headers=_h(keys["bob"]),
        )
        still_listed = await _listed_ids(client, keys["alice"])
        carol_delete = await client.delete(
            f"/api/v1/knowledge/documents/{doc}", headers=_h(keys["carol"])
        )
        audit = await client.get("/api/v1/admin/audit-log", headers=_h(keys["carol"]))
        gone = await _listed_ids(client, keys["alice"])

    assert bob_delete.status_code == 403
    assert bob_grant.status_code == 403
    assert still_listed == {doc}
    assert carol_delete.status_code == 204
    assert gone == set()
    entries = [e for e in audit.json() if e["action"] == "knowledge.delete"]
    assert len(entries) == 1
    assert entries[0]["actor_id"] == "carol"
    assert entries[0]["resource_owner_id"] == "alice"
    assert entries[0]["resource_id"] == doc


async def test_grant_gives_access_and_revoke_removes_it() -> None:
    """Verify sharing with one user works, excludes others, and revocation takes effect."""
    async with _app() as (client, keys):
        doc = await _ingest(
            client, keys["alice"], title="Quarterly plan", content="delta budget forecast"
        )
        before = await _titles_in_search(client, keys["bob"], "delta budget")

        grant = await client.post(
            f"/api/v1/knowledge/documents/{doc}/grants",
            json={"grantee_id": "bob"},
            headers=_h(keys["alice"]),
        )
        summary = [
            d
            for d in (
                await client.get("/api/v1/knowledge/documents", headers=_h(keys["alice"]))
            ).json()
            if d["id"] == doc
        ][0]
        bob_after = await _titles_in_search(client, keys["bob"], "delta budget")
        carol_after = await _titles_in_search(client, keys["carol"], "delta budget")
        bob_listing = await _listed_ids(client, keys["bob"])
        grants = await client.get(
            f"/api/v1/knowledge/documents/{doc}/grants", headers=_h(keys["alice"])
        )

        revoke = await client.delete(
            f"/api/v1/knowledge/documents/{doc}/grants/bob", headers=_h(keys["alice"])
        )
        revoke_again = await client.delete(
            f"/api/v1/knowledge/documents/{doc}/grants/bob", headers=_h(keys["alice"])
        )
        bob_revoked = await _titles_in_search(client, keys["bob"], "delta budget")

    assert before == set()
    assert grant.status_code == 201
    assert summary["visibility"] == "shared"
    assert bob_after == {"Quarterly plan"}
    assert carol_after == set()
    assert bob_listing == {doc}
    assert [g["grantee_id"] for g in grants.json()] == ["bob"]
    assert revoke.status_code == 204
    assert revoke_again.status_code == 404
    assert bob_revoked == set()


async def test_grantee_can_read_but_cannot_manage_the_document() -> None:
    """Verify a granted user gets 403 (not 404) when trying to manage a shared document."""
    async with _app() as (client, keys):
        doc = await _ingest(client, keys["alice"], title="Design doc", content="epsilon design")
        await client.post(
            f"/api/v1/knowledge/documents/{doc}/grants",
            json={"grantee_id": "bob"},
            headers=_h(keys["alice"]),
        )
        delete = await client.delete(
            f"/api/v1/knowledge/documents/{doc}", headers=_h(keys["bob"])
        )
        regrant = await client.post(
            f"/api/v1/knowledge/documents/{doc}/grants",
            json={"grantee_id": "carol"},
            headers=_h(keys["bob"]),
        )

    assert delete.status_code == 403
    assert regrant.status_code == 403


async def test_changing_visibility_changes_who_can_search() -> None:
    """Verify private -> tenant -> private immediately opens and closes access."""
    async with _app() as (client, keys):
        doc = await _ingest(client, keys["alice"], title="Wiki page", content="zeta wiki entry")
        closed = await _titles_in_search(client, keys["bob"], "zeta wiki")

        opened = await client.patch(
            f"/api/v1/knowledge/documents/{doc}/visibility",
            json={"visibility": "tenant"},
            headers=_h(keys["alice"]),
        )
        open_hits = await _titles_in_search(client, keys["bob"], "zeta wiki")

        await client.patch(
            f"/api/v1/knowledge/documents/{doc}/visibility",
            json={"visibility": "private"},
            headers=_h(keys["alice"]),
        )
        closed_again = await _titles_in_search(client, keys["bob"], "zeta wiki")

    assert closed == set()
    assert opened.status_code == 200
    assert opened.json()["visibility"] == "tenant"
    assert open_hits == {"Wiki page"}
    assert closed_again == set()


async def test_search_with_explicit_document_ids_cannot_reach_foreign_documents() -> None:
    """Verify guessing another user's document id does not bypass visibility filtering."""
    async with _app() as (client, keys):
        doc = await _ingest(client, keys["alice"], title="Private memo", content="eta memo text")
        response = await client.post(
            "/api/v1/knowledge/search",
            json={"query": "eta memo", "min_score": 0.0, "document_ids": [doc]},
            headers=_h(keys["bob"]),
        )

    assert response.status_code == 200
    assert response.json() == []


async def test_dedupe_is_per_tenant_not_global() -> None:
    """Verify identical content is allowed in two tenants but rejected twice in one."""
    async with _app() as (client, keys):
        content = "theta identical onboarding text"
        await _ingest(client, keys["alice"], title="Original", content=content)
        other_tenant = await client.post(
            "/api/v1/knowledge/documents",
            json={"title": "Copy in globex", "content": content},
            headers=_h(keys["dave"]),
        )
        same_tenant = await client.post(
            "/api/v1/knowledge/documents",
            json={"title": "Copy in acme", "content": content},
            headers=_h(keys["bob"]),
        )

    assert other_tenant.status_code == 201
    assert same_tenant.status_code == 409


async def test_invalid_visibility_is_rejected() -> None:
    """Verify unknown visibility values fail request validation."""
    async with _app() as (client, keys):
        response = await client.post(
            "/api/v1/knowledge/documents",
            json={"title": "x", "content": "iota", "visibility": "public"},
            headers=_h(keys["alice"]),
        )

    assert response.status_code == 422
