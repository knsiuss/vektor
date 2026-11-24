import asyncio
import json
import tempfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

RENDERER_VERSION = "v1"


class RenderConversionError(Exception):
    """Raised when document conversion fails or times out."""


@dataclass(frozen=True)
class RenderResult:
    cache_key: str
    content: bytes
    media_type: str
    cached: bool


def compute_render_cache_key(
    source: dict[str, Any],
    renderer_version: str = RENDERER_VERSION,
) -> str:
    """Compute deterministic cache key from IR source and renderer version."""
    canonical = json.dumps(source, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = sha256(canonical.encode("utf-8")).hexdigest()
    return f"{digest}:{renderer_version}"


def verify_pdf_bytes(data: bytes) -> bool:
    """Verify basic structural validity of generated PDF bytes."""
    return len(data) > 8 and data.startswith(b"%PDF-")


class ArtifactRenderPipeline:
    """Sandboxed document render pipeline with bounded sha256 disk caching."""

    def __init__(
        self,
        cache_dir: Path | None = None,
        timeout_seconds: int = 60,
        max_cache_entries: int = 200,
    ) -> None:
        self._cache_dir = cache_dir or (Path(tempfile.gettempdir()) / "vektor_render_cache")
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._timeout_seconds = timeout_seconds
        self._max_cache_entries = max_cache_entries

    def _cache_path(self, cache_key: str, ext: str) -> Path:
        return self._cache_dir / f"{cache_key.replace(':', '_')}.{ext}"

    def _evict_if_needed(self) -> None:
        files = sorted(
            (p for p in self._cache_dir.iterdir() if p.is_file()),
            key=lambda p: p.stat().st_mtime,
        )
        excess = len(files) - self._max_cache_entries
        for old in files[: max(0, excess)]:
            old.unlink(missing_ok=True)

    def get_cached(self, cache_key: str, ext: str = "pdf") -> bytes | None:
        path = self._cache_path(cache_key, ext)
        if path.is_file():
            return path.read_bytes()
        return None

    def put_cached(self, cache_key: str, data: bytes, ext: str = "pdf") -> None:
        path = self._cache_path(cache_key, ext)
        path.write_bytes(data)
        self._evict_if_needed()

    async def convert_office_to_pdf(
        self,
        input_bytes: bytes,
        input_ext: str,
        source_ir: dict[str, Any],
    ) -> RenderResult:
        """Convert docx/pptx/xlsx bytes to PDF via headless LibreOffice with caching."""
        cache_key = compute_render_cache_key(source_ir)
        cached = await asyncio.to_thread(self.get_cached, cache_key, "pdf")
        if cached is not None:
            return RenderResult(
                cache_key=cache_key,
                content=cached,
                media_type="application/pdf",
                cached=True,
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            in_file = tmp_path / f"input.{input_ext.lstrip('.')}"
            await asyncio.to_thread(in_file.write_bytes, input_bytes)

            proc = await asyncio.create_subprocess_exec(
                "soffice",
                "--headless",
                "--norestore",
                "--nolockcheck",
                "--convert-to",
                "pdf",
                "--outdir",
                str(tmp_path),
                str(in_file),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                _, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=self._timeout_seconds,
                )
            except TimeoutError as exc:
                proc.kill()
                raise RenderConversionError("convert_timeout") from exc

            if proc.returncode != 0:
                raise RenderConversionError(stderr.decode("utf-8", errors="replace")[:300])

            out_file = tmp_path / "input.pdf"
            if not out_file.is_file():
                raise RenderConversionError("PDF output file was not produced.")
            pdf_bytes = await asyncio.to_thread(out_file.read_bytes)
            if not verify_pdf_bytes(pdf_bytes):
                raise RenderConversionError("Generated PDF failed structural verification.")

            await asyncio.to_thread(self.put_cached, cache_key, pdf_bytes, "pdf")
            return RenderResult(
                cache_key=cache_key,
                content=pdf_bytes,
                media_type="application/pdf",
                cached=False,
            )
