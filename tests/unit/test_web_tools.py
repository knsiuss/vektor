from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from modules.ai_runtime.grounding import verify_grounding
from modules.ai_runtime.service import ChatService, _WebTurnState
from modules.knowledge.schemas import RetrievedChunk
from modules.tools.web import (
    WebOptions,
    WebToolError,
    ensure_public_url,
    extract_readable_text,
    fetch_web_page,
    normalize_search_results,
    search_web,
    urls_in_text,
)


def _call(name: str, arguments: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(id="call-1", name=name, arguments=arguments)


def _service() -> ChatService:
    # The guard only reads the web settings and never touches these collaborators.
    return ChatService(provider=None, repository=None, web_max_searches=2, web_max_fetches=1)  # type: ignore[arg-type]


def test_extract_readable_text_drops_scripts_and_normalizes() -> None:
    title, text = extract_readable_text(
        "<html><head><title>DB  failover</title><style>x{}</style></head>"
        "<body><script>alert('no')</script><p>Run  failover</p><p>now</p></body></html>",
        max_chars=200,
    )
    assert title == "DB  failover"
    assert "alert" not in text
    assert "Run failover" in text
    assert text.count("\n") <= 3


def test_normalize_search_results_rejects_non_http_and_caps() -> None:
    rows = [
        {"title": "One", "href": "https://example.com/a", "body": "first"},
        {"title": "Bad", "href": "javascript:alert(1)", "body": "nope"},
        {"title": "Two", "href": "https://example.com/b", "body": "second"},
        {"title": "Three", "href": "https://example.com/c", "body": "third"},
    ]
    results = normalize_search_results(rows, limit=2)
    assert [row["url"] for row in results] == [
        "https://example.com/a",
        "https://example.com/b",
    ]
    assert results[0]["snippet"] == "first"


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "http://169.254.169.254/latest/meta-data/",
        "http://localhost:8000/",
        "file:///etc/passwd",
        "ftp://example.com/file",
        "https://user:pass@example.com/",
        "https://example.com:8443/",
    ],
)
async def test_ensure_public_url_blocks_internal_and_odd_targets(url: str) -> None:
    with pytest.raises(WebToolError):
        await ensure_public_url(url)


async def test_ensure_public_url_blocks_hostname_resolving_private(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_resolve(host: str, port: int) -> list[str]:
        return ["10.0.0.7"]

    monkeypatch.setattr("modules.tools.web._resolve_addresses", fake_resolve)
    with pytest.raises(WebToolError, match="private or reserved"):
        await ensure_public_url("https://internal.example.com/docs")


async def test_fetch_web_page_rejects_redirect_to_internal(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_resolve(host: str, port: int) -> list[str]:
        return ["93.184.216.34"]

    monkeypatch.setattr("modules.tools.web._resolve_addresses", fake_resolve)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://127.0.0.1/secret"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(WebToolError):
            await fetch_web_page("https://example.com/start", options=WebOptions(), client=client)


async def test_fetch_web_page_returns_title_and_text(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_resolve(host: str, port: int) -> list[str]:
        return ["93.184.216.34"]

    monkeypatch.setattr("modules.tools.web._resolve_addresses", fake_resolve)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text=(
                "<html><head><title>Pricing</title></head>"
                "<body><p>Plan A costs $10.</p></body></html>"
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        page = await fetch_web_page(
            "https://example.com/pricing", options=WebOptions(), client=client
        )

    assert page["title"] == "Pricing"
    assert "Plan A costs $10." in page["text"]
    assert page["retrieved_at"].endswith("+00:00")


async def test_fetch_web_page_rejects_unsupported_content_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_resolve(host: str, port: int) -> list[str]:
        return ["93.184.216.34"]

    monkeypatch.setattr("modules.tools.web._resolve_addresses", fake_resolve)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/pdf"},
            content=b"%PDF-1.7",
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(WebToolError, match="Unsupported content type"):
            await fetch_web_page("https://example.com/report", options=WebOptions(), client=client)


async def test_search_web_normalizes_duckduckgo_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_search(query: str, limit: int) -> list[dict[str, Any]]:
        assert query == "postgres 17 release"
        return [{"title": "Postgres 17", "href": "https://example.com/pg17", "body": "Released"}]

    monkeypatch.setattr("modules.tools.web._duckduckgo_search", fake_search)
    results = await search_web("  postgres   17 release  ", options=WebOptions())
    assert results == [
        {"title": "Postgres 17", "url": "https://example.com/pg17", "snippet": "Released"}
    ]


async def test_search_web_uses_configured_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    async def fake_search(
        query: str, limit: int, *, base_url: str, client: httpx.AsyncClient | None = None
    ) -> list[dict[str, Any]]:
        seen.append(base_url)
        return [{"title": "Postgres 17", "url": "https://example.com/pg17", "content": "Released"}]

    monkeypatch.setattr("modules.tools.web._searxng_search", fake_search)
    results = await search_web(
        "postgres 17",
        options=WebOptions(searxng_url="https://searx.example"),
        provider="searxng",
    )
    assert seen == ["https://searx.example"]
    assert results[0]["snippet"] == "Released"


async def test_search_web_fails_over_between_public_instances(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[str] = []

    async def fake_search(
        query: str, limit: int, *, base_url: str, client: httpx.AsyncClient | None = None
    ) -> list[dict[str, Any]]:
        attempts.append(base_url)
        if base_url == "https://searx.be":
            raise WebToolError("instance down")
        return [{"title": "Hit", "url": "https://example.com/hit", "content": "ok"}]

    monkeypatch.setattr("modules.tools.web._searxng_search", fake_search)
    results = await search_web("query", options=WebOptions(), provider="searxng")
    assert attempts == ["https://searx.be", "https://search.inetol.net"]
    assert results[0]["url"] == "https://example.com/hit"


async def test_search_web_reports_unavailable_when_all_instances_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_search(
        query: str, limit: int, *, base_url: str, client: httpx.AsyncClient | None = None
    ) -> list[dict[str, Any]]:
        raise WebToolError("instance down")

    monkeypatch.setattr("modules.tools.web._searxng_search", fake_search)
    with pytest.raises(WebToolError, match="unavailable"):
        await search_web("query", options=WebOptions(), provider="searxng")


def test_urls_in_text_strips_trailing_punctuation() -> None:
    text = "Compare https://example.com/a, and https://example.com/b."
    assert urls_in_text(text) == {"https://example.com/a", "https://example.com/b"}


def test_web_guard_blocks_fetch_before_search() -> None:
    service = _service()
    state = _WebTurnState()
    blocked = service._web_guard(_call("web_fetch", {"url": "https://example.com/"}), state)
    assert blocked is not None
    assert blocked.status == "blocked"
    assert "web_search" in blocked.output


def test_web_guard_allows_user_url_and_enforces_fetch_limit() -> None:
    service = _service()
    state = _WebTurnState(allowed_urls={"https://example.com/docs"})
    first = service._web_guard(_call("web_fetch", {"url": "https://example.com/docs"}), state)
    assert first is None
    second = service._web_guard(_call("web_fetch", {"url": "https://example.com/docs"}), state)
    assert second is not None
    assert second.status == "blocked"


def _web_page() -> RetrievedChunk:
    return RetrievedChunk(
        document_id="https://example.com/news",
        document_title="Example news",
        chunk_index=0,
        content="Prices rose 5% in March.",
        semantic_score=0.0,
        lexical_score=0.0,
        score=0.0,
        kind="web",
        url="https://example.com/news",
        retrieved_at="2026-11-24T00:00:00+00:00",
    )


def test_web_only_citations_do_not_trigger_missing_citation_warning() -> None:
    report = verify_grounding("Harga naik 5 persen.", [_web_page()])
    assert report.has_context_without_citations is False


def test_document_citations_still_require_inline_citation() -> None:
    chunk = _web_page().model_copy(update={"kind": "document", "url": None, "retrieved_at": None})
    report = verify_grounding("Harga naik 5 persen.", [chunk])
    assert report.has_context_without_citations is True


def test_web_guard_enforces_search_limit_and_collects_urls() -> None:
    service = _service()
    state = _WebTurnState()
    assert service._web_guard(_call("web_search", {"query": "one"}), state) is None
    assert service._web_guard(_call("web_search", {"query": "two"}), state) is None
    third = service._web_guard(_call("web_search", {"query": "three"}), state)
    assert third is not None and third.status == "blocked"

    service._remember_web_urls(
        "web_search",
        '{"results": [{"url": "https://example.com/a"}]}',
        state,
    )
    assert state.allowed_urls == {"https://example.com/a"}
