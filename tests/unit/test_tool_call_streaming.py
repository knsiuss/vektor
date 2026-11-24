import json

from modules.model_gateway.openai_compatible import OpenAICompatibleProvider
from modules.model_gateway.schemas import ToolCallDelta
from modules.model_gateway.tool_calls import ToolCallAccumulator


def test_arguments_split_across_chunks_are_joined() -> None:
    """Verify one call whose JSON arguments arrive in pieces becomes one complete call."""
    acc = ToolCallAccumulator()
    acc.add([ToolCallDelta(index=0, id="call_a", name="search", arguments="")])
    acc.add([ToolCallDelta(index=0, arguments='{"que')])
    acc.add([ToolCallDelta(index=0, arguments='ry": "fail')])
    acc.add([ToolCallDelta(index=0, arguments='over"}')])

    assert acc.has_calls
    calls = acc.build()
    assert [(c.id, c.name) for c in calls] == [("call_a", "search")]
    assert json.loads(calls[0].arguments) == {"query": "failover"}


def test_parallel_calls_on_different_indexes_keep_their_order() -> None:
    """Verify two simultaneous calls are kept apart and returned in the order produced."""
    acc = ToolCallAccumulator()
    acc.add([ToolCallDelta(index=0, id="c0", name="first", arguments="{")])
    acc.add([ToolCallDelta(index=1, id="c1", name="second", arguments="{}")])
    acc.add([ToolCallDelta(index=0, arguments="}")])

    calls = acc.build()
    assert [(c.id, c.name, c.arguments) for c in calls] == [
        ("c0", "first", "{}"),
        ("c1", "second", "{}"),
    ]


def test_new_id_on_a_reused_index_starts_a_new_call() -> None:
    """Verify providers that reuse index 0 for several calls do not merge them."""
    acc = ToolCallAccumulator()
    acc.add([ToolCallDelta(index=0, id="x", name="one", arguments="{}")])
    acc.add([ToolCallDelta(index=0, id="y", name="two", arguments="{}")])

    assert [(c.id, c.name) for c in acc.build()] == [("x", "one"), ("y", "two")]


def test_missing_id_gets_a_stable_fallback_and_empty_arguments_become_an_object() -> None:
    """Verify a call without id or arguments is still executable."""
    acc = ToolCallAccumulator()
    acc.add([ToolCallDelta(index=2, name="get_system_health")])

    (call,) = acc.build()
    assert call.id.startswith("call_")
    assert call.name == "get_system_health"
    assert call.arguments == "{}"


def test_fragments_without_a_name_are_ignored() -> None:
    """Verify a stray fragment that never gets a name does not produce a call."""
    acc = ToolCallAccumulator()
    acc.add([ToolCallDelta(index=0, arguments='{"orphan": true}')])

    assert not acc.has_calls
    assert acc.build() == []


def _parse(payload: dict[str, object]):  # type: ignore[no-untyped-def]
    provider = OpenAICompatibleProvider(api_key=None, provider_name="test")
    return provider._parse_stream_chunk(json.dumps(payload), "fallback-model")


def test_provider_parses_streamed_tool_call_fragments() -> None:
    """Verify an OpenAI-style delta with tool_calls becomes ToolCallDelta objects."""
    chunk = _parse(
        {
            "model": "m",
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {"name": "echo", "arguments": '{"a"'},
                            }
                        ]
                    }
                }
            ],
        }
    )

    assert chunk is not None
    assert chunk.delta == ""
    assert [(d.index, d.id, d.name, d.arguments) for d in chunk.tool_call_deltas] == [
        (0, "call_1", "echo", '{"a"')
    ]


def test_provider_tolerates_malformed_tool_call_fragments() -> None:
    """Verify odd shapes (no function, dict arguments, no index) never raise."""
    chunk = _parse(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            "not-a-dict",
                            {"id": "k"},
                            {"function": {"name": "x", "arguments": {"a": 1}}},
                        ]
                    }
                }
            ]
        }
    )

    assert chunk is not None
    assert [d.arguments for d in chunk.tool_call_deltas] == ["", '{"a": 1}']
    assert chunk.tool_call_deltas[1].index == 2


def test_chunk_with_only_text_has_no_tool_call_deltas() -> None:
    """Verify ordinary answer chunks are unchanged by the tool-call parsing."""
    chunk = _parse({"choices": [{"delta": {"content": "hello"}}]})

    assert chunk is not None
    assert chunk.delta == "hello"
    assert chunk.tool_call_deltas == []
