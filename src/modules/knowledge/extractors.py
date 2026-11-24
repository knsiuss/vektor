import base64
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from typing import Any

import docx
import httpx
from pydantic import SecretStr
from pypdf import PdfReader

_TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".csv", ".json", ".yaml", ".yml", ".log"}
_MAX_PDF_PAGES = 500
_IMAGE_MIME_TYPES: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


class UnsupportedDocumentError(Exception):
    """Raised when an uploaded file format is unsupported or cannot be parsed."""


class DocumentExtractor:
    """Extracts clean structured text from PDF, DOCX, Markdown/Text, and Images."""

    def __init__(
        self,
        *,
        api_key: SecretStr | None = None,
        base_url: str = "https://api.openai.com/v1",
        vision_model: str = "gpt-4o-mini",
        timeout_seconds: float = 45.0,
        client: httpx.AsyncClient | None = None,
        on_usage: Callable[[str, int, int, int], None] | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._vision_model = vision_model
        self._timeout_seconds = timeout_seconds
        self._external_client = client
        self._on_usage = on_usage

    async def extract(self, *, filename: str, content_bytes: bytes) -> str:
        """Route file bytes to the appropriate format parser and return normalized text."""
        if not content_bytes:
            raise UnsupportedDocumentError("Uploaded file is empty.")

        ext = Path(filename).suffix.lower()
        if ext in _TEXT_EXTENSIONS:
            return self._extract_text(content_bytes)
        if ext == ".pdf":
            return self._extract_pdf(content_bytes)
        if ext == ".docx":
            return self._extract_docx(content_bytes)
        if ext in _IMAGE_MIME_TYPES:
            return await self._extract_image(content_bytes, mime_type=_IMAGE_MIME_TYPES[ext])

        raise UnsupportedDocumentError(
            f"Unsupported file type '{ext or 'unknown'}'. "
            "Supported: .txt, .md, .csv, .json, .pdf, .docx, .png, .jpg, .jpeg, .webp."
        )

    def _extract_text(self, content_bytes: bytes) -> str:
        try:
            text = content_bytes.decode("utf-8")
        except UnicodeDecodeError:
            text = content_bytes.decode("latin-1")
        cleaned = text.strip()
        if not cleaned:
            raise UnsupportedDocumentError("Text document contains no readable content.")
        return cleaned

    def _extract_pdf(self, content_bytes: bytes) -> str:
        try:
            reader = PdfReader(BytesIO(content_bytes))
        except Exception as exc:
            raise UnsupportedDocumentError("Failed to read PDF structure.") from exc

        if len(reader.pages) > _MAX_PDF_PAGES:
            raise UnsupportedDocumentError(
                f"PDF exceeds the maximum of {_MAX_PDF_PAGES} pages."
            )

        pages: list[str] = []
        for idx, page in enumerate(reader.pages, start=1):
            extracted = (page.extract_text() or "").strip()
            if extracted:
                pages.append(f"## Page {idx}\n{extracted}")

        if not pages:
            raise UnsupportedDocumentError("PDF contains no extractable text.")
        return "\n\n".join(pages)

    def _extract_docx(self, content_bytes: bytes) -> str:
        try:
            document = docx.Document(BytesIO(content_bytes))
        except Exception as exc:
            raise UnsupportedDocumentError("Failed to read DOCX document.") from exc

        blocks: list[str] = []
        for para in document.paragraphs:
            text = para.text.strip()
            if not text:
                continue
            style_name = para.style.name.lower() if para.style and para.style.name else ""
            if style_name.startswith("heading"):
                blocks.append(f"## {text}")
            else:
                blocks.append(text)

        for table in document.tables:
            for row in table.rows:
                cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
                if any(cells):
                    blocks.append(" | ".join(cells))

        if not blocks:
            raise UnsupportedDocumentError("DOCX document contains no readable text.")
        return "\n\n".join(blocks)

    async def _extract_image(self, content_bytes: bytes, *, mime_type: str) -> str:
        if self._api_key is None or not self._api_key.get_secret_value().strip():
            raise UnsupportedDocumentError("Vision extraction requires a configured LLM API key.")

        encoded = base64.b64encode(content_bytes).decode("ascii")
        payload: dict[str, Any] = {
            "model": self._vision_model,
            "temperature": 0.1,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Extract all visible text, error codes, tables, and key "
                                "technical details into clean Markdown without commentary."
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime_type};base64,{encoded}"},
                        },
                    ],
                }
            ],
        }
        headers = {
            "Authorization": f"Bearer {self._api_key.get_secret_value().strip()}",
            "Content-Type": "application/json",
        }
        url = f"{self._base_url}/chat/completions"

        try:
            if self._external_client is not None:
                resp = await self._external_client.post(
                    url, json=payload, headers=headers, timeout=self._timeout_seconds
                )
            else:
                async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                    resp = await client.post(url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise UnsupportedDocumentError(
                "Vision API call failed during image ingestion."
            ) from exc

        if resp.status_code >= 400:
            raise UnsupportedDocumentError(
                f"Vision API rejected image ingestion with HTTP {resp.status_code}."
            )

        data = resp.json()
        choices = data.get("choices") if isinstance(data, dict) else None
        if not isinstance(choices, list) or not choices:
            raise UnsupportedDocumentError("Vision API returned empty extraction.")
        content = choices[0].get("message", {}).get("content")
        if not isinstance(content, str) or not content.strip():
            raise UnsupportedDocumentError("No readable text extracted from image.")

        usage = data.get("usage") if isinstance(data, dict) else None
        if self._on_usage is not None and isinstance(usage, dict):
            self._on_usage(
                self._vision_model,
                int(usage.get("prompt_tokens") or 0),
                int(usage.get("completion_tokens") or 0),
                int(usage.get("total_tokens") or 0),
            )
        return content.strip()
