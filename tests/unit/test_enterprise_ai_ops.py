from datetime import UTC, datetime, timedelta

import pytest

from modules.ai_runtime.pii import PIIScrubber
from modules.approvals.repository import ApprovalStateError, validate_approval_transition
from modules.evals.runner import evaluate_reply, summarize_eval_results
from modules.knowledge.freshness_audit import DocumentSummary, audit_knowledge_documents


def test_pii_scrubber_redacts_and_restores() -> None:
    scrubber = PIIScrubber()
    text = "Email saya budi@example.com, HP 081234567890, NIK 3201010101990001."
    res = scrubber.redact(text)
    assert "budi@example.com" not in res.sanitized
    assert "081234567890" not in res.sanitized
    assert "3201010101990001" not in res.sanitized
    assert "[REDACTED_EMAIL_1]" in res.sanitized
    assert "[REDACTED_PHONE_1]" in res.sanitized
    assert "[REDACTED_NIK_1]" in res.sanitized
    assert scrubber.restore(res.sanitized, res.mapping) == text


def test_knowledge_freshness_and_conflict_audit() -> None:
    now = datetime(2026, 11, 24, tzinfo=UTC)
    docs = [
        DocumentSummary(
            id="d1", title="Kebijakan Garansi 2025", updated_at=now - timedelta(days=120)
        ),
        DocumentSummary(
            id="d2", title="Kebijakan Garansi 2026", updated_at=now - timedelta(days=5)
        ),
        DocumentSummary(
            id="d3", title="Panduan Onboarding Karyawan", updated_at=now - timedelta(days=2)
        ),
    ]
    report = audit_knowledge_documents(docs, freshness_ttl_days=90, now=now)
    assert report.stale_doc_ids == ["d1"]
    assert len(report.conflicts) == 1
    assert {report.conflicts[0].doc_a_id, report.conflicts[0].doc_b_id} == {"d1", "d2"}


def test_eval_runner_scoring() -> None:
    r1 = evaluate_reply(
        case_id="c1",
        question="Berapa lama garansi?",
        reply="Garansi resmi berlaku 14 hari sejak pembelian.",
        expected_facts=["14 hari"],
        forbidden_claims=["seumur hidup"],
    )
    r2 = evaluate_reply(
        case_id="c2",
        question="Bisa refund?",
        reply="Refund seumur hidup tersedia.",
        expected_facts=["7 hari"],
        forbidden_claims=["seumur hidup"],
    )
    assert r1.passed is True
    assert r2.passed is False
    assert r2.missing_facts == ["7 hari"]
    assert r2.triggered_forbidden == ["seumur hidup"]
    summary = summarize_eval_results([r1, r2])
    assert summary.total == 2
    assert summary.passed == 1
    assert summary.pass_rate == 0.5


def test_approval_state_transitions() -> None:
    validate_approval_transition("pending", "approved")
    validate_approval_transition("pending", "rejected")
    validate_approval_transition("approved", "executed")
    with pytest.raises(ApprovalStateError):
        validate_approval_transition("rejected", "approved")
    with pytest.raises(ApprovalStateError):
        validate_approval_transition("executed", "executed")
