import re

import httpx

from modules.knowledge.repository import KnowledgeRepository
from modules.knowledge.schemas import DocumentSummary
from modules.llm_gateway.ssrf import validate_custom_base_url

_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")


def extract_plain_text(html_or_text: str) -> str:
    """Strip HTML tags and normalize whitespace for clean KB indexing."""
    without_scripts = re.sub(
        r"<(script|style)[^>]*>.*?</\1>", " ", html_or_text, flags=re.IGNORECASE | re.DOTALL
    )
    stripped = _TAG_RE.sub(" ", without_scripts)
    return _SPACE_RE.sub(" ", stripped).strip()


async def sync_url_to_knowledge(
    *,
    url: str,
    title: str,
    kb_repo: KnowledgeRepository,
    http_client: httpx.AsyncClient,
) -> DocumentSummary:
    """Fetch a public HTTPS URL (SSRF-validated) and ingest its text into Knowledge Base."""
    safe_url = validate_custom_base_url(url, allow_local=False)
    response = await http_client.get(safe_url, timeout=20.0, follow_redirects=False)
    response.raise_for_status()
    text = extract_plain_text(response.text)
    if not text:
        raise ValueError("Fetched URL produced empty text content.")
    return await kb_repo.ingest_document(
        title=title,
        content=text[:100_000],
        source=safe_url,
        visibility="tenant",
    )
