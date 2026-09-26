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
        "social_copy": "用一段完整原话解释这个话题，帮助你快速理解关键观点。",
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
    assert result.suggestions[0].social_copy.startswith("用一段完整原话")
    assert result.notes == ("只有两个独立话题",)
    payload = json.loads(provider.requests[0].user_prompt)
    assert payload["segments"][0]["duration_ms"] == 30000
    assert "API" not in provider.requests[0].user_prompt


def test_discovery_mode_omits_publication_copy_without_an_extra_request() -> None:
    import asyncio

    row = candidate(["a"])
    row.pop("social_copy")
    provider = FakeProvider({"candidates": [row], "notes": []})
    result = asyncio.run(
        HighlightPlanner(provider).plan(
            HighlightBrief.for_preset(HighlightPreset.KNOWLEDGE),
            source(),
            publication_metadata=False,
        )
    )
    assert len(provider.requests) == 1
    assert result.suggestions[0].social_copy is None
    payload = json.loads(provider.requests[0].user_prompt)
    assert "social_copy" not in payload["output_example"]["candidates"][0]


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


@pytest.mark.parametrize(
    "preset", [HighlightPreset.CLEAN_SPEECH, HighlightPreset.OPINION]
)
@pytest.mark.parametrize("mode", ["continuous", "compact"])
@pytest.mark.parametrize("hook", [None, 5000])
def test_structural_controls_override_conflicting_preset_text(
    preset: HighlightPreset, mode: str, hook: int | None
) -> None:
    import asyncio

    provider = FakeProvider({"candidates": [], "notes": []})
    brief = HighlightBrief.for_preset(
        preset, body_mode=mode, hook_ms=hook, preset_prompt="删除重复并把结论放开头"
    )
    asyncio.run(HighlightPlanner(provider).plan(brief, source()))
    payload = json.loads(provider.requests[0].user_prompt)
    requirements = payload["final_requirements"]
    assert ("不得跳切" in requirements["body_mode"]) == (mode == "continuous")
    assert ("必须为 []" in requirements["hook"]) == (hook is None)
    assert payload["brief"]["body_mode"] == mode
    assert payload["brief"]["hook_ms"] == hook


def test_extra_root_metadata_does_not_discard_valid_candidates() -> None:
    import asyncio

    brief = HighlightBrief.for_preset(HighlightPreset.PODCAST)
    provider = FakeProvider(
        {"candidates": [candidate(["a"])], "notes": [], "type": "highlights"}
    )
    result = asyncio.run(HighlightPlanner(provider).plan(brief, source()))
    assert len(result.suggestions) == 1
    assert len(provider.requests) == 1
    with pytest.raises(ValueError, match="unknown"):
        asyncio.run(
            HighlightPlanner(
                FakeProvider(
                    {
                        "candidates": [candidate(["invented"])],
                        "notes": [],
                        "type": "highlights",
                    }
                )
            ).plan(brief, source())
        )


def test_bad_candidate_does_not_discard_other_valid_candidates() -> None:
    import asyncio

    invalid = candidate(["c"])
    invalid["context_segment_ids"] = ["invented-background"]
    provider = FakeProvider(
        {"candidates": [candidate(["a"]), invalid, candidate(["b"])], "notes": []}
    )
    result = asyncio.run(
        HighlightPlanner(provider).plan(
            HighlightBrief.for_preset(HighlightPreset.PODCAST), source()
        )
    )
    assert [s.candidate.segment_ids for s in result.suggestions] == [("a",), ("b",)]
    assert any("已跳过" in n for n in result.notes)
    assert len(provider.requests) == 1
