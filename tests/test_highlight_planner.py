import json

import pytest

from minicut.highlight_brief import HighlightBrief, HighlightPreset
from minicut.highlight_planner import HighlightPlanner
from minicut.llm_provider import TextModelRequest, TextModelResponse
from minicut.semantic_segment import SemanticSegment


class FakeProvider:
    def __init__(self, data: object) -> None:
        self.data = data
        self.requests: list[TextModelRequest] = []

    async def generate(self, request: TextModelRequest) -> TextModelResponse:
        self.requests.append(request)
        return TextModelResponse(json.dumps(self.data), request.model)


def source() -> tuple[SemanticSegment, ...]:
    return tuple(
        SemanticSegment(s, s, i * 30000, (i + 1) * 30000, (s,), (s,))
        for i, s in enumerate(("a", "b", "c", "d"))
    )


def candidate(ids: list[str]) -> dict[str, object]:
    return {
        "title": "解释",
        "reason": "完整论述",
        "segment_ids": ids,
        "context_segment_ids": [],
        "hook_segment_ids": [],
    }


def test_single_request_multiple_candidates_and_insufficiency() -> None:
    import asyncio

    provider = FakeProvider(
        {
            "candidates": [candidate(["a", "b"]), candidate(["c", "d"])],
            "notes": ["只有两个独立话题"],
        }
    )
    result = asyncio.run(
        HighlightPlanner(provider).plan(
            HighlightBrief.for_preset(HighlightPreset.KNOWLEDGE), source()
        )
    )
    assert len(provider.requests) == 1
    assert len(result.suggestions) == 2
    assert result.notes == ("只有两个独立话题",)
    payload = json.loads(provider.requests[0].user_prompt)
    assert payload["segments"][0]["duration_ms"] == 30000
    assert "API" not in provider.requests[0].user_prompt


@pytest.mark.parametrize(
    "data",
    [
        {"candidates": [candidate(["unknown"])], "notes": []},
        {"candidates": [candidate(["a", "a"])], "notes": []},
        {"candidates": {}, "notes": []},
    ],
)
def test_bad_response_rejected(data: object) -> None:
    import asyncio

    with pytest.raises(ValueError):
        asyncio.run(
            HighlightPlanner(FakeProvider(data)).plan(
                HighlightBrief.for_preset(HighlightPreset.PODCAST), source()
            )
        )


def test_empty_candidates_are_allowed() -> None:
    import asyncio

    result = asyncio.run(
        HighlightPlanner(FakeProvider({"candidates": [], "notes": ["素材不足"]})).plan(
            HighlightBrief.for_preset(HighlightPreset.PODCAST), source()
        )
    )
    assert result.suggestions == ()


def test_long_source_ids_use_local_aliases_and_resolve_back() -> None:
    import asyncio
    from dataclasses import replace

    segments = (replace(source()[0], segment_id="segment:" + "x" * 100),)
    provider = FakeProvider({"candidates": [candidate(["s-1"])], "notes": []})
    result = asyncio.run(
        HighlightPlanner(provider).plan(
            HighlightBrief.for_preset(HighlightPreset.KNOWLEDGE), segments
        )
    )
    assert result.suggestions[0].candidate.segment_ids == (segments[0].segment_id,)
    assert (
        json.loads(provider.requests[0].user_prompt)["segments"][0]["segment_id"]
        == "s-1"
    )


def test_variable_brief_follows_identical_source_prefix() -> None:
    import asyncio
    from dataclasses import replace

    provider = FakeProvider({"candidates": [], "notes": []})
    brief = HighlightBrief.for_preset(HighlightPreset.KNOWLEDGE)
    asyncio.run(HighlightPlanner(provider).plan(brief, source()))
    asyncio.run(
        HighlightPlanner(provider).plan(
            replace(brief, instructions="different"), source()
        )
    )
    left, right = [r.user_prompt for r in provider.requests]
    assert left.split('"brief":')[0] == right.split('"brief":')[0]
    assert left != right


@pytest.mark.parametrize("repair_succeeds", [True, False])
def test_malformed_json_gets_only_one_format_repair(repair_succeeds: bool) -> None:
    import asyncio

    class MalformedProvider(FakeProvider):
        async def generate(self, request: TextModelRequest) -> TextModelResponse:
            self.requests.append(request)
            content = '{"title": "a "quoted" title"}'
            if repair_succeeds and len(self.requests) == 2:
                content = json.dumps({"candidates": [candidate(["a"])], "notes": []})
            return TextModelResponse(content, request.model)

    provider = MalformedProvider(None)
    operation = HighlightPlanner(provider).plan(
        HighlightBrief.for_preset(HighlightPreset.KNOWLEDGE), source()
    )
    if repair_succeeds:
        result = asyncio.run(operation)
        assert result.suggestions[0].candidate.segment_ids == ("a",)
    else:
        with pytest.raises(ValueError, match="一次格式修复"):
            asyncio.run(operation)
    assert len(provider.requests) == 2
    assert json.loads(provider.requests[1].user_prompt)["format_repair"][
        "invalid_response"
    ]


@pytest.mark.parametrize("notes, expected", [("素材说明", ("素材说明",)), ("", ())])
def test_single_note_text_is_preserved_without_model_retry(
    notes: str, expected: tuple[str, ...]
) -> None:
    import asyncio

    provider = FakeProvider({"candidates": [candidate(["a"])], "notes": notes})
    result = asyncio.run(
        HighlightPlanner(provider).plan(
            HighlightBrief.for_preset(HighlightPreset.PODCAST), source()
        )
    )
    assert result.notes == expected
    assert len(result.suggestions) == 1
    assert len(provider.requests) == 1


@pytest.mark.parametrize("notes", [None, {}, [1]])
def test_invalid_notes_are_still_rejected(notes: object) -> None:
    import asyncio

    with pytest.raises(ValueError, match="模型返回"):
        asyncio.run(
            HighlightPlanner(FakeProvider({"candidates": [], "notes": notes})).plan(
                HighlightBrief.for_preset(HighlightPreset.PODCAST), source()
            )
        )
