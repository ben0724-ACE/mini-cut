from dataclasses import replace

import pytest

from minicut.chapter_planner import chapter_windows, source_size
from minicut.semantic_segment import (
    ContextDirection,
    SegmentContextDependency,
    SemanticSegment,
)


def test_chapters_cover_tail_and_keep_context_with_budget() -> None:
    segments = tuple(
        SemanticSegment(
            f"s{i}", "text " * 50, i * 1000, (i + 1) * 1000, (f"u{i}",), (f"w{i}",)
        )
        for i in range(9)
    )
    segments = tuple(
        replace(
            s,
            context_dependencies=(
                SegmentContextDependency("s2", ContextDirection.PRECEDING),
            ),
        )
        if i == 3
        else s
        for i, s in enumerate(segments)
    )
    windows = chapter_windows(segments, 1600)
    assert {s.segment_id for w in windows for s in w} == {
        s.segment_id for s in segments
    }
    assert all(source_size(w) <= 1600 for w in windows)
    assert all(
        any(s.segment_id == "s2" for s in w)
        for w in windows
        if any(s.segment_id == "s3" for s in w)
    )
    assert windows[-1][-1].segment_id == "s8"


def test_oversized_context_is_explicit_not_truncated() -> None:
    segment = SemanticSegment("s", "long " * 1000, 0, 1000, ("u",), ("w",))
    with pytest.raises(ValueError, match="budget"):
        chapter_windows((segment,), 1000)


def test_hierarchical_selection_refines_original_sources() -> None:
    import asyncio
    import json

    from minicut.chapter_planner import plan_chapters
    from minicut.highlight_brief import HighlightBrief, HighlightPreset
    from minicut.highlight_planner import HighlightPlanner
    from minicut.llm_provider import TextModelRequest, TextModelResponse

    sources = tuple(
        SemanticSegment(
            f"s{i}",
            "explanation " * 70,
            i * 30000,
            (i + 1) * 30000,
            (f"u{i}",),
            (f"w{i}",),
        )
        for i in range(24)
    )
    calls: list[TextModelRequest] = []

    class Provider:
        async def generate(self, request: TextModelRequest) -> TextModelResponse:
            calls.append(request)
            payload = json.loads(request.user_prompt)
            if payload.get("version") == "chapter-selection-v1":
                return TextModelResponse(
                    json.dumps({"ids": [payload["candidates"][-1]["id"]]}),
                    request.model,
                )
            ids = [s["segment_id"] for s in payload["segments"][:2]]
            return TextModelResponse(
                json.dumps(
                    {
                        "candidates": [
                            {
                                "title": "topic",
                                "reason": "complete",
                                "segment_ids": ids,
                                "context_segment_ids": [],
                                "hook_segment_ids": [],
                            }
                        ],
                        "notes": [],
                    }
                ),
                request.model,
            )

    result, original = asyncio.run(
        plan_chapters(
            HighlightPlanner(Provider()),
            HighlightBrief.for_preset(HighlightPreset.KNOWLEDGE),
            sources,
        )
    )
    assert len(calls) >= 4
    assert set(result.suggestions[0].candidate.segment_ids) <= {
        s.segment_id for s in original
    }
    assert len(original) < len(sources)
    assert json.loads(calls[-1].user_prompt)["segments"][0]["text"] in [
        s.text for s in sources
    ]


def test_chapter_selection_uses_ranked_candidates_within_budget() -> None:
    import asyncio
    import json

    from minicut.chapter_planner import plan_chapters
    from minicut.highlight_brief import HighlightBrief, HighlightPreset
    from minicut.highlight_planner import HighlightPlanner
    from minicut.llm_provider import TextModelRequest, TextModelResponse

    sources = tuple(
        SemanticSegment(
            f"s{i}",
            "explanation " * 70,
            i * 30000,
            (i + 1) * 30000,
            (f"u{i}",),
            (f"w{i}",),
        )
        for i in range(48)
    )
    ranked: list[str] = []
    selected_source_ids: list[str] = []

    class Provider:
        async def generate(self, request: TextModelRequest) -> TextModelResponse:
            payload = json.loads(request.user_prompt)
            if payload.get("version") == "chapter-selection-v1":
                ranked.extend(
                    candidate["id"] for candidate in payload["candidates"][:3]
                )
                return TextModelResponse(
                    json.dumps({"ids": [*ranked, ranked[0]]}), request.model
                )
            ids = [segment["segment_id"] for segment in payload["segments"][:2]]
            if payload["brief"]["count"] == 1:
                selected_source_ids.extend(
                    segment["segment_id"] for segment in payload["segments"]
                )
            return TextModelResponse(
                json.dumps(
                    {
                        "candidates": [
                            {
                                "title": "topic",
                                "reason": "complete",
                                "segment_ids": ids,
                                "context_segment_ids": [],
                                "hook_segment_ids": [],
                            }
                        ],
                        "notes": [],
                    }
                ),
                request.model,
            )

    brief = replace(HighlightBrief.for_preset(HighlightPreset.PODCAST), count=1)
    result, original = asyncio.run(
        plan_chapters(HighlightPlanner(Provider()), brief, sources)
    )
    assert result.suggestions
    assert len(ranked) == 3
    assert len(original) == 4
    assert selected_source_ids == [segment.segment_id for segment in original]
