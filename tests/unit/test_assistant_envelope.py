from modules.ai_runtime.envelope import parse_assistant_output, strip_status_markers


def test_plain_text_is_an_answer() -> None:
    """Legacy output without a marker must keep working unchanged."""
    envelope = parse_assistant_output("Replication lag is 4s on replica 2.")

    assert envelope.status == "answer"
    assert envelope.answer == "Replication lag is 4s on replica 2."


def test_marker_with_text_sets_the_status() -> None:
    envelope = parse_assistant_output(
        "<<status=clarify>> Toko mana yang dimaksud: Tangsel atau Jakarta?"
    )

    assert envelope.status == "clarify"
    assert envelope.clarifying_question == "Toko mana yang dimaksud: Tangsel atau Jakarta?"
    assert envelope.display_text == envelope.clarifying_question


def test_clarify_accepts_a_json_body_with_options() -> None:
    raw = (
        "<<status=clarify>>\n"
        '{"question": "Toko mana yang dimaksud?", '
        '"options": ["Toko Tangsel", "Toko Jakarta", "Toko Bandung", "Semua toko", "Ekstra"]}'
    )

    envelope = parse_assistant_output(raw)

    assert envelope.status == "clarify"
    assert envelope.clarifying_question == "Toko mana yang dimaksud?"
    # Capped at four so the UI cannot turn into a wall of buttons.
    assert envelope.options == ["Toko Tangsel", "Toko Jakarta", "Toko Bandung", "Semua toko"]


def test_json_in_a_markdown_fence_is_understood() -> None:
    raw = (
        '```json\n'
        '{"status": "answer", "answer": "OK", "evidence": [{"kind": "citation", "index": 1}]}\n'
        '```'
    )

    envelope = parse_assistant_output(raw)

    assert envelope.status == "answer"
    assert envelope.answer == "OK"
    assert envelope.evidence[0].index == 1


def test_unknown_status_keeps_the_explanation() -> None:
    envelope = parse_assistant_output(
        "<<status=unknown>> Tidak ada dokumen runbook failover di knowledge base."
    )

    assert envelope.status == "unknown"
    assert "runbook" in envelope.answer


def test_clarify_without_a_question_degrades_to_unknown() -> None:
    """A question is mandatory; otherwise the status is not usable."""
    envelope = parse_assistant_output("<<status=clarify>>")

    assert envelope.status == "unknown"


def test_broken_json_falls_back_to_text_instead_of_erroring() -> None:
    raw = '<<status=clarify>> {"question": "Toko mana?", "options": [}'

    envelope = parse_assistant_output(raw)

    assert envelope.status == "clarify"
    assert "Toko mana?" in envelope.clarifying_question


def test_unknown_marker_is_coerced_to_answer() -> None:
    envelope = parse_assistant_output("<<status=banana>> Halo")

    assert envelope.status == "answer"
    assert envelope.answer == "Halo"


def test_options_are_deduplicated_and_trimmed() -> None:
    raw = '<<status=clarify>> {"question": "Pilih?", "options": [" A ", "A", "", "B"]}'

    envelope = parse_assistant_output(raw)

    assert envelope.options == ["A", "B"]


def test_multiple_sentences_are_reduced_to_one_question() -> None:
    raw = "<<status=clarify>> Toko mana? Sebutkan juga periodenya ya."

    envelope = parse_assistant_output(raw)

    assert envelope.clarifying_question == "Toko mana?"


def test_marker_after_a_tool_preamble_is_honoured() -> None:
    """Tool-using models often write a sentence before the envelope marker."""
    envelope = parse_assistant_output(
        "Let me check the replica status. <<status=clarify>> Toko mana?"
    )

    assert envelope.status == "clarify"
    assert envelope.clarifying_question == "Toko mana?"


def test_bare_json_with_status_is_understood_without_a_marker() -> None:
    """Some models emit the schema directly instead of the marker contract."""
    envelope = parse_assistant_output(
        '{"status": "unknown", "answer": "Tidak ada data runbook."}'
    )

    assert envelope.status == "unknown"
    assert envelope.answer == "Tidak ada data runbook."


def test_strip_status_markers_removes_every_marker() -> None:
    text = "<<status=answer>> Halo <<status=clarify>> dunia"

    assert strip_status_markers(text) == " Halo  dunia"
