from pathlib import Path

from modules.artifacts.evidence import truncate_source_snippet, validate_ir_evidence
from modules.artifacts.renderer import (
    ArtifactRenderPipeline,
    compute_render_cache_key,
    verify_pdf_bytes,
)


def test_validate_ir_evidence_flags_unverified_numbers() -> None:
    ir = {
        "schema_version": 1,
        "blocks": [
            {
                "id": "b1",
                "type": "paragraph",
                "spans": [{"text": "Omzet naik 12,4%"}],
            },
            {
                "id": "b2",
                "type": "paragraph",
                "spans": [{"text": "Laba "}, {"text": "Rp 500", "evidence": "ev_1"}],
            },
        ],
    }
    assert validate_ir_evidence(ir) == ["b1"]


def test_truncate_source_snippet() -> None:
    assert truncate_source_snippet("abc", max_chars=5) == "abc"
    assert truncate_source_snippet("abcdef", max_chars=3).endswith("... [truncated]")


def test_render_cache_key_deterministic_and_cache_hit(tmp_path: Path) -> None:
    ir = {"blocks": [{"id": "b1", "type": "heading", "text": "Hi"}]}
    k1 = compute_render_cache_key(ir)
    k2 = compute_render_cache_key({"blocks": [{"type": "heading", "text": "Hi", "id": "b1"}]})
    assert k1 == k2

    pipeline = ArtifactRenderPipeline(cache_dir=tmp_path)
    assert pipeline.get_cached(k1) is None
    pipeline.put_cached(k1, b"%PDF-1.4\n...")
    assert pipeline.get_cached(k1) == b"%PDF-1.4\n..."
    assert verify_pdf_bytes(b"%PDF-1.4\n...") is True
    assert verify_pdf_bytes(b"not-a-pdf") is False
