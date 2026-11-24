"""Token budgeting for the conversation history that is sent back to the model."""

from collections.abc import Sequence

from modules.conversations.models import Conversation, ConversationMessage
from modules.conversations.schemas import ConversationContext, ConversationDetail, MessageItem

CHARS_PER_TOKEN = 4

# Roles that survive compaction and are replayed to the model on later turns.
REPLAYABLE_ROLES = ("user", "assistant", "summary")


def estimate_tokens(text: str) -> int:
    """Estimate tokens from character count; deliberately cheap and provider-agnostic."""
    return max(1, len(text) // CHARS_PER_TOKEN)


def select_budgeted_history(
    history: Sequence[ConversationMessage],
    *,
    max_messages: int,
    max_tokens: int,
) -> list[ConversationMessage]:
    """Keep the newest replayable messages that fit both the count and token budgets."""
    if max_messages <= 0:
        return []

    candidates = [item for item in history[-max_messages:] if item.role in REPLAYABLE_ROLES]
    selected: list[ConversationMessage] = []
    used_tokens = 0

    for item in reversed(candidates):
        msg_tokens = estimate_tokens(item.content)
        if selected and used_tokens + msg_tokens > max_tokens:
            break
        selected.append(item)
        used_tokens += msg_tokens

    selected.reverse()
    return selected


def describe_context(
    history: Sequence[ConversationMessage],
    *,
    max_messages: int,
    max_tokens: int,
) -> ConversationContext:
    """Report how much of the prompt window the stored history currently occupies."""
    included = select_budgeted_history(
        history,
        max_messages=max_messages,
        max_tokens=max_tokens,
    )
    return ConversationContext(
        used_tokens=sum(estimate_tokens(item.content) for item in included),
        limit_tokens=max_tokens,
        included_messages=len(included),
        total_messages=sum(1 for item in history if item.role in REPLAYABLE_ROLES),
    )


def build_conversation_detail(
    conversation: Conversation,
    *,
    max_messages: int,
    max_tokens: int,
) -> ConversationDetail:
    """Serialize a conversation together with its current prompt-window usage."""
    return ConversationDetail(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=[MessageItem.model_validate(item) for item in conversation.messages],
        context=describe_context(
            conversation.messages,
            max_messages=max_messages,
            max_tokens=max_tokens,
        ),
    )
