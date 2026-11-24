from collections.abc import Iterable

from modules.model_gateway.schemas import ModelToolCall, ToolCallDelta


class _Slot:
    __slots__ = ("arguments", "id", "name", "order")

    def __init__(self, order: int) -> None:
        self.order = order
        self.id = ""
        self.name = ""
        self.arguments = ""


class ToolCallAccumulator:
    """Joins streamed tool-call fragments into complete ModelToolCall objects.

    OpenAI-style streams send a call's id and name once and its JSON arguments in many
    small pieces, keyed by ``index``. Some providers reuse one index for several calls and
    tell them apart only by id, so a new id on a used index starts a new call.
    """

    def __init__(self) -> None:
        self._slots: list[_Slot] = []
        self._by_index: dict[int, _Slot] = {}

    def add(self, deltas: Iterable[ToolCallDelta]) -> None:
        for delta in deltas:
            slot = self._by_index.get(delta.index)
            if slot is not None and delta.id and slot.id and delta.id != slot.id:
                slot = None
            if slot is None:
                slot = _Slot(order=len(self._slots))
                self._slots.append(slot)
                self._by_index[delta.index] = slot
            if delta.id and not slot.id:
                slot.id = delta.id
            if delta.name:
                if not slot.name:
                    slot.name = delta.name
                elif delta.name != slot.name:
                    slot.name += delta.name
            slot.arguments += delta.arguments

    @property
    def has_calls(self) -> bool:
        return any(slot.name for slot in self._slots)

    def build(self) -> list[ModelToolCall]:
        """Return the finished calls in the order the model produced them."""
        calls: list[ModelToolCall] = []
        for slot in sorted(self._slots, key=lambda item: item.order):
            if not slot.name:
                continue
            calls.append(
                ModelToolCall(
                    id=slot.id or f"call_{slot.order}",
                    name=slot.name,
                    arguments=slot.arguments.strip() or "{}",
                )
            )
        return calls
