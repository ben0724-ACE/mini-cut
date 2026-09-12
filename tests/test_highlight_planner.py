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
