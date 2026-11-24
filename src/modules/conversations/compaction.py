"""Compress older conversation turns into one summary so later prompts stay small."""

from collections.abc import Sequence
from datetime import timedelta

from modules.ai_runtime.envelope import parse_assistant_output
from modules.conversations.models import Conversation, ConversationMessage
from modules.conversations.repository import ConversationNotFoundError, ConversationRepository
from modules.model_gateway.base import LLMProvider
from modules.model_gateway.schemas import ChatMessage, ModelRequest

SUMMARY_ROLE = "summary"
SUMMARY_PREFIX = "[Earlier conversation summary]"
DEFAULT_KEEP_LAST = 4
MAX_TRANSCRIPT_CHARS = 12000

_COMPACTION_PROMPT = (
    "You compress chat history for an AI operations assistant. "
    "Summarize the transcript in at most 8 short bullet points. "
    "Keep decisions, identifiers, commands, errors, and open questions. "
    "Drop pleasantries and repetition. Answer with the bullets only."
)


class ConversationCompactor:
    """Replace old turns with one provider-written summary message."""

    def __init__(
        self,
        provider: LLMProvider,
        repository: ConversationRepository,
        *,
        keep_last: int = DEFAULT_KEEP_LAST,
        max_transcript_chars: int = MAX_TRANSCRIPT_CHARS,
    ) -> None:
        self._provider = provider
        self._repository = repository
        self._keep_last = max(1, keep_last)
        self._max_transcript_chars = max_transcript_chars

    async def compact(self, conversation_id: str) -> Conversation:
        """Summarize everything except the newest turns; return the refreshed conversation."""
        conversation = await self._repository.get_conversation(conversation_id)
        if conversation is None:
            raise ConversationNotFoundError(conversation_id)

        replayable = [item for item in conversation.messages if item.role in ("user", "assistant")]
        if len(replayable) <= self._keep_last:
            return conversation

        older = replayable[: -self._keep_last]
        response = await self._provider.generate(
            ModelRequest(
                messages=[
                    ChatMessage(role="system", content=_COMPACTION_PROMPT),
                    ChatMessage(role="user", content=self._transcript(older)),
                ],
                temperature=0.0,
            )
        )
        # The summarizer is a chat model too: it may wrap its output in the reply envelope.
        summary = parse_assistant_output(response.content).display_text.strip()
        if not summary:
            return conversation

        await self._repository.replace_messages_with_summary(
            conversation=conversation,
            message_ids=[item.id for item in older],
            content=f"{SUMMARY_PREFIX}\n{summary}",
            # Sort just ahead of the oldest surviving turn so the summary leads the history.
            created_at=older[0].created_at - timedelta(microseconds=1),
        )
        refreshed = await self._repository.get_conversation(conversation_id)
        return refreshed or conversation

    def _transcript(self, messages: Sequence[ConversationMessage]) -> str:
        lines = [f"{item.role}: {item.content}" for item in messages]
        transcript = "\n\n".join(lines)
        if len(transcript) > self._max_transcript_chars:
            # Keep the tail: the most recent turns carry the most context.
            transcript = "...[truncated]\n" + transcript[-self._max_transcript_chars :]
        return transcript
