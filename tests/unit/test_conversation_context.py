from modules.conversations.context import (
    describe_context,
    estimate_tokens,
    select_budgeted_history,
)
from modules.conversations.models import ConversationMessage


def _message(role: str, content: str, index: int = 0) -> ConversationMessage:
    return ConversationMessage(
        id=f"m{index}",
        conversation_id="c1",
        role=role,
        content=content,
        prompt_tokens=0,
        completion_tokens=0,
        total_tokens=0,
    )


def test_estimate_tokens_never_returns_zero() -> None:
    """Empty content still costs something so budgeting cannot loop forever."""
    assert estimate_tokens("") == 1
    assert estimate_tokens("abcdefgh") == 2


def test_select_keeps_newest_messages_within_token_budget() -> None:
    """When the budget is tight the oldest turns are dropped, newest kept."""
    history = [
        _message("user", "a" * 400, 0),
        _message("assistant", "b" * 400, 1),
        _message("user", "c" * 40, 2),
    ]

    selected = select_budgeted_history(history, max_messages=20, max_tokens=50)

    assert [item.id for item in selected] == ["m2"]


def test_select_keeps_a_single_oversized_newest_message() -> None:
    """One huge message is still sent; otherwise the model would see no history at all."""
    history = [_message("user", "x" * 4000, 0)]

    selected = select_budgeted_history(history, max_messages=20, max_tokens=10)

    assert len(selected) == 1


def test_select_ignores_non_replayable_roles() -> None:
    """System/tool rows are not replayed and must not consume the budget."""
    history = [
        _message("tool", "tool output", 0),
        _message("user", "hello", 1),
        _message("summary", "[Earlier conversation summary]", 2),
    ]

    selected = select_budgeted_history(history, max_messages=20, max_tokens=3500)

    assert [item.role for item in selected] == ["user", "summary"]


def test_describe_context_counts_replayable_messages_only() -> None:
    """Usage reports the prompt window, not every stored row."""
    history = [
        _message("user", "a" * 400, 0),
        _message("assistant", "b" * 400, 1),
        _message("tool", "ignored", 2),
    ]

    context = describe_context(history, max_messages=20, max_tokens=120)

    assert context.limit_tokens == 120
    assert context.total_messages == 2
    assert context.included_messages == 1
    assert context.used_tokens == 100
