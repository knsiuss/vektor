from modules.ai_runtime.retriever import _parse_rewrite_output


def test_two_line_reply_sets_query_and_ambiguity() -> None:
    raw = "QUERY: replication lag replica 2\nAMBIGUOUS: yes"

    query, ambiguous = _parse_rewrite_output(raw, "fallback")

    assert query == "replication lag replica 2"
    assert ambiguous is True


def test_ambiguous_no_is_not_treated_as_ambiguous() -> None:
    query, ambiguous = _parse_rewrite_output("QUERY: failover runbook\nAMBIGUOUS: no", "fallback")

    assert query == "failover runbook"
    assert ambiguous is False


def test_missing_query_line_falls_back_to_the_first_line() -> None:
    """An older model that ignores the format still yields a usable search query."""
    query, ambiguous = _parse_rewrite_output('"postgres vacuum"\nAMBIGUOUS: yes', "fallback")

    assert query == "postgres vacuum"
    assert ambiguous is True


def test_empty_reply_uses_the_caller_fallback() -> None:
    query, ambiguous = _parse_rewrite_output("", "omzet bulan lalu")

    assert query == "omzet bulan lalu"
    assert ambiguous is False


def test_no_search_token_is_preserved() -> None:
    query, _ = _parse_rewrite_output("QUERY: NO_SEARCH\nAMBIGUOUS: no", "halo")

    assert query == "NO_SEARCH"
