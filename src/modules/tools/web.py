"""No-API web tools: DuckDuckGo (default) or SearXNG search, plus a guarded page fetch.

Web content is untrusted input. `fetch_web_page` refuses non-public hosts before every
request and redirect, caps the body, and only accepts text content. Callers must still treat
the returned text as data, never as instructions.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import socket
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

_ALLOWED_SCHEMES = {"http", "https"}
_ALLOWED_PORTS = {None, 80, 443}
_ALLOWED_CONTENT_TYPES = {"text/html", "application/xhtml+xml", "text/plain"}
_BLOCKED_HOST_SUFFIXES = (".local", ".internal", ".localhost", ".home.arpa")
_MAX_REDIRECTS = 3
_USER_AGENT = "VektorBot/0.1 (+https://github.com/knsiuss/vektor)"
# Public SearXNG instances used when no instance URL is configured. Tried in order; a
# deployment should point VEKTOR_WEB_SEARXNG_URL at its own instance for stable results.
_DEFAULT_SEARXNG_URLS = (
    "https://searx.be",
    "https://search.inetol.net",
    "https://baresearch.org",
)
_WHITESPACE = re.compile(r"[ \t\r\f\v]+")
_BLANK_LINES = re.compile(r"\n{3,}")


class WebToolError(Exception):
    """A web tool could not complete safely; the message is safe to show the model."""


@dataclass(frozen=True)
class WebOptions:
    """Limits applied to every search and fetch."""

    max_results: int = 5
    fetch_timeout_seconds: float = 10.0
    max_bytes: int = 2_000_000
    max_page_chars: int = 6000
    searxng_url: str | None = None


class _PageText(HTMLParser):
    """Collect visible text and the document title, dropping script/style payloads."""

    _SKIPPED = {"script", "style", "noscript", "svg", "template", "iframe"}
    _BREAKS = {
        "p", "div", "br", "li", "tr", "section", "article",
        "h1", "h2", "h3", "h4", "h5", "h6",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIPPED:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag in self._BREAKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIPPED and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in self._BREAKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self.title += data
        else:
            self.parts.append(data)


def extract_readable_text(html: str, *, max_chars: int) -> tuple[str, str]:
    """Return (title, visible text) with whitespace normalized and length capped."""
    parser = _PageText()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 - malformed markup must not fail a fetch
        pass
    text = "".join(parser.parts)
    text = _WHITESPACE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    text = _BLANK_LINES.sub("\n\n", text).strip()
    return parser.title.strip(), text[:max_chars]


def _is_blocked_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return not ip.is_global


async def _resolve_addresses(host: str, port: int) -> list[str]:
    try:
        infos = await asyncio.to_thread(
            socket.getaddrinfo,
            host,
            port,
            type=socket.SOCK_STREAM,
        )
    except OSError as exc:
        raise WebToolError(f"Could not resolve host '{host}'.") from exc
    return sorted({str(info[4][0]) for info in infos})


async def ensure_public_url(url: str) -> str:
    """Validate scheme, port, host shape and resolved addresses; return the URL unchanged."""
    parsed = urlparse(url.strip())
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise WebToolError("Only http and https URLs can be fetched.")
    if parsed.username or parsed.password:
        raise WebToolError("URLs with embedded credentials are not allowed.")
    if parsed.port not in _ALLOWED_PORTS:
        raise WebToolError("Only ports 80 and 443 can be fetched.")
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        raise WebToolError("URL is missing a host.")
    if host == "localhost" or host.endswith(_BLOCKED_HOST_SUFFIXES):
        raise WebToolError("Internal hosts cannot be fetched.")

    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if _is_blocked_ip(str(literal)):
            raise WebToolError("Private or reserved addresses cannot be fetched.")
        return url

    addresses = await _resolve_addresses(host, parsed.port or 80)
    if not addresses:
        raise WebToolError(f"Could not resolve host '{host}'.")
    for address in addresses:
        if _is_blocked_ip(address):
            raise WebToolError("Host resolves to a private or reserved address.")
    return url


async def _read_capped(response: httpx.Response, limit: int) -> bytes:
    body = bytearray()
    async for chunk in response.aiter_bytes():
        body.extend(chunk)
        if len(body) >= limit:
            return bytes(body[:limit])
    return bytes(body)


def _page_payload(url: str, title: str, text: str) -> dict[str, Any]:
    return {
        "url": url,
        "title": title or url,
        "retrieved_at": datetime.now(UTC).isoformat(),
        "text": text,
    }


async def fetch_web_page(
    url: str,
    *,
    options: WebOptions,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Fetch one page with SSRF, size and content-type guards; return its visible text."""
    own_client = client is None
    active = client or httpx.AsyncClient(
        timeout=options.fetch_timeout_seconds,
        follow_redirects=False,
        headers={"User-Agent": _USER_AGENT},
    )
    current = url
    try:
        for _ in range(_MAX_REDIRECTS + 1):
            await ensure_public_url(current)
            response = await active.get(current)
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("location")
                if not location:
                    raise WebToolError("The page redirected without a location.")
                current = urljoin(current, location)
                continue
            if response.status_code >= 400:
                raise WebToolError(f"The page returned HTTP {response.status_code}.")
            content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
            if content_type not in _ALLOWED_CONTENT_TYPES:
                raise WebToolError(f"Unsupported content type '{content_type or 'unknown'}'.")
            raw = await _read_capped(response, options.max_bytes)
            encoding = response.encoding or "utf-8"
            try:
                document = raw.decode(encoding, errors="replace")
            except LookupError:
                document = raw.decode("utf-8", errors="replace")
            if content_type == "text/plain":
                title = ""
                text = document[: options.max_page_chars]
            else:
                title, text = extract_readable_text(document, max_chars=options.max_page_chars)
            if not text.strip():
                raise WebToolError("The page contained no readable text.")
            return _page_payload(str(response.url), title, text)
        raise WebToolError("The page redirected too many times.")
    except httpx.HTTPError as exc:
        raise WebToolError(f"Could not fetch the page: {exc}") from exc
    finally:
        if own_client:
            await active.aclose()


def normalize_search_results(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, str]]:
    """Map provider-specific rows to `{title, url, snippet}` and drop unusable entries."""
    results: list[dict[str, str]] = []
    for row in rows:
        url = str(row.get("href") or row.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        results.append(
            {
                "title": str(row.get("title") or url).strip(),
                "url": url,
                "snippet": str(row.get("body") or row.get("content") or "").strip(),
            }
        )
        if len(results) >= limit:
            break
    return results


async def _duckduckgo_search(query: str, limit: int) -> list[dict[str, Any]]:
    def _run() -> list[dict[str, Any]]:
        from ddgs import DDGS

        return list(DDGS().text(query, max_results=limit))

    try:
        return await asyncio.to_thread(_run)
    except Exception as exc:  # noqa: BLE001 - provider errors are all shown as unavailable
        raise WebToolError("DuckDuckGo search is unavailable right now.") from exc


async def _searxng_search(
    query: str,
    limit: int,
    *,
    base_url: str,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    parsed = urlparse(base_url)
    if parsed.scheme not in _ALLOWED_SCHEMES or not parsed.hostname:
        raise WebToolError("The configured SearXNG URL is invalid.")
    own_client = client is None
    active = client or httpx.AsyncClient(timeout=10.0, headers={"User-Agent": _USER_AGENT})
    try:
        response = await active.get(
            urljoin(base_url.rstrip("/") + "/", "search"),
            params={"q": query, "format": "json", "safesearch": "1"},
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise WebToolError("SearXNG search is unavailable right now.") from exc
    finally:
        if own_client:
            await active.aclose()
    rows = payload.get("results") if isinstance(payload, dict) else None
    return list(rows or [])[:limit]


def normalize_query(raw: str) -> str:
    """Collapse whitespace and cap length so cache keys and provider input stay stable."""
    return " ".join(raw.split())[:200]


async def search_web(
    query: str,
    *,
    options: WebOptions,
    provider: str = "duckduckgo",
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, str]]:
    """Search the web and return normalized results; raises WebToolError on failure."""
    cleaned = normalize_query(query)
    if not cleaned:
        raise WebToolError("'query' must contain search terms.")
    if provider == "searxng":
        instances = (
            [options.searxng_url] if options.searxng_url else list(_DEFAULT_SEARXNG_URLS)
        )
        rows: list[dict[str, Any]] = []
        errors: list[str] = []
        for instance in instances:
            try:
                rows = await _searxng_search(
                    cleaned, options.max_results, base_url=instance, client=client
                )
            except WebToolError as exc:
                errors.append(f"{instance}: {exc}")
                continue
            if rows:
                break
        if not rows:
            detail = errors[0] if errors else "no instance returned results"
            raise WebToolError(f"SearXNG search is unavailable right now ({detail}).")
    else:
        rows = await _duckduckgo_search(cleaned, options.max_results)
    results = normalize_search_results(rows, limit=options.max_results)
    if not results:
        raise WebToolError("No search results were returned.")
    return results


def urls_in_text(text: str) -> set[str]:
    """Extract http(s) URLs a user typed, so they may be fetched without a search first."""
    found = re.findall(r"https?://[^\s<>\"')]+", text)
    return {item.rstrip(".,;:") for item in found}


def dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False)
