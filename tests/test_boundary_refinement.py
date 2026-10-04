import asyncio
import json
from dataclasses import replace

import pytest

from minicut.boundary_refinement import build_boundary_request, refine_boundaries
from minicut.highlight_brief import HighlightBrief, HighlightPreset
from minicut.highlight_selection import select_highlights
from minicut.sentence_boundaries import sentence_segments
from minicut.transcript import Transcript, TranscriptSource, Word
from tests.test_highlight_planner import FakeProvider
from tests.test_highlight_selection import proposal


@pytest.mark.parametrize("version", [None, 3])
def test_semantic_word_ids_refine_unpunctuated_body_without_holes(
    version: int | None,
) -> None:
    transcript = Transcript(
        "t",
        TranscriptSource("a", "test", "test"),
        "zh",
        tuple(Word(f"w{i}", "内容", i * 1000, i * 1000 + 900) for i in range(60)),
    )
    segments = sentence_segments(transcript)
    brief = HighlightBrief.for_preset(
        HighlightPreset.PODCAST,
        boundary_version=version,
        count=1,
        min_ms=10000,
        max_ms=60000,
        hook_ms=5000,
    )
    initial = select_highlights(
        proposal((segments[1].segment_id, segments[2].segment_id)),
        brief,
        segments,
        "a",
        "c",
    )
    provider = FakeProvider(
        {
            "ranges": [
                {
                    "output_id": "video-1",
                    "start_id": "12",
                    "end_id": "43",
                    "hook_start_id": "20",
                    "hook_end_id": "24",
                }
            ]
        }
    )
    result = asyncio.run(
        refine_boundaries(initial, brief, transcript, segments, provider, "fake", 60000)
    )
    assert result.collection is not None
    hook, body = result.collection.plans[0].items
    assert (body.source_start_ms, body.source_end_ms) == (11900, 44000)
    assert (hook.source_start_ms, hook.source_end_ms) == (20000, 24900)
    bad = FakeProvider(
        {
            "ranges": [
                {
                    "output_id": "video-1",
                    "start_id": "999999",
                    "end_id": "43",
                    "hook_start_id": "0",
                    "hook_end_id": "59",
                }
            ]
        }
    )
    fallback = asyncio.run(
        refine_boundaries(initial, brief, transcript, segments, bad, "fake", 60000)
    )
    assert fallback.collection is not None and initial.collection is not None
    assert fallback.collection.plans[0].items == initial.collection.plans[0].items
    assert any("建议检查" in n for n in fallback.notes)
    tight = asyncio.run(
        refine_boundaries(
            initial,
            replace(brief, max_ms=12000),
            transcript,
            segments,
            provider,
            "fake",
            60000,
        )
    )
    assert tight.collection is None


@pytest.mark.parametrize("version", [None, 3])
def test_custom_ten_second_hook_survives_word_boundary_review(
    version: int | None,
) -> None:
    import json

    transcript = Transcript(
        "t",
        TranscriptSource("a", "test", "test"),
        "zh",
        tuple(Word(f"w{i}", "内容", i * 1000, i * 1000 + 900) for i in range(60)),
    )
    segments = sentence_segments(transcript)
    brief = HighlightBrief.for_preset(
        HighlightPreset.PODCAST,
        boundary_version=version,
        count=1,
        min_ms=10000,
        max_ms=60000,
        hook_ms=10000,
    )
    initial = select_highlights(
        proposal((segments[1].segment_id, segments[2].segment_id)),
        brief,
        segments,
        "a",
        "c",
    )
    provider = FakeProvider(
        {
            "ranges": [
                {
                    "output_id": "video-1",
                    "start_id": "12",
                    "end_id": "43",
                    "hook_start_id": "20",
                    "hook_end_id": "29",
                }
            ]
        }
    )
    result = asyncio.run(
        refine_boundaries(initial, brief, transcript, segments, provider, "fake", 60000)
    )
    assert result.collection is not None
    hook = result.collection.plans[0].items[0]
    assert (hook.source_start_ms, hook.source_end_ms) == (20000, 29900)
    payload = json.loads(provider.requests[0].user_prompt)
    assert payload["hook_target_ms"] == 10000
    assert payload["hook_bounds_ms"] == [7000, 13000]


@pytest.mark.parametrize("version", [None, 3])
def test_null_review_preserves_valid_initial_hook_but_not_outside_new_body(
    version: int | None,
) -> None:
    from minicut.output_plan import OutputItem, OutputRole

    transcript = Transcript(
        "t",
        TranscriptSource("a", "test", "test"),
        "zh",
        tuple(Word(f"w{i}", "内容。", i * 1000, i * 1000 + 900) for i in range(30)),
    )
    segments = sentence_segments(transcript)
    brief = HighlightBrief.for_preset(
        HighlightPreset.PODCAST,
        boundary_version=version,
        count=1,
        min_ms=1000,
        max_ms=60000,
        hook_ms=5000,
    )
    initial = select_highlights(
        proposal(tuple(s.segment_id for s in segments[:20])), brief, segments, "a", "c"
    )
    assert initial.collection is not None
    plan = initial.collection.plans[0]
    hook = OutputItem(
        "hook",
        segments[1].segment_id,
        OutputRole.HOOK,
        source_start_ms=1000,
        source_end_ms=5900,
    )
    initial = replace(
        initial,
        collection=replace(
            initial.collection, plans=(replace(plan, items=(hook, *plan.items)),)
        ),
    )
    for start_id, expected in [("0", True), ("8", False)]:
        provider = FakeProvider(
            {
                "ranges": [
                    {
                        "output_id": "video-1",
                        "start_id": start_id,
                        "end_id": "19",
                        "hook_start_id": None,
                        "hook_end_id": None,
                    }
                ]
            }
        )
        result = asyncio.run(
            refine_boundaries(
                initial, brief, transcript, segments, provider, "fake", 30000
            )
        )
        assert result.collection is not None
        assert (
            any(i.role is OutputRole.HOOK for i in result.collection.plans[0].items)
            == expected
        )


@pytest.mark.parametrize("version", [None, 3])
def test_refined_body_reanchors_when_old_first_segment_is_excluded(
    version: int | None,
) -> None:
    from minicut.highlight_selection import HighlightSelection
    from minicut.output_plan import (
        HighlightCandidate,
        OutputCollection,
        OutputItem,
        OutputPlan,
        OutputRole,
        validate_output_collection,
    )

    transcript = Transcript(
        "t",
        TranscriptSource("a", "test", "test"),
        "zh",
        tuple(Word(f"w{i}", "内容。", i * 1000, i * 1000 + 900) for i in range(20)),
    )
    segments = sentence_segments(transcript)
    candidate = HighlightCandidate(
        "candidate-1",
        "topic",
        "reason",
        (segments[5].segment_id,),
        (segments[4].segment_id,),
    )
    body = OutputItem(
        "video-1-body-0",
        segments[4].segment_id,
        OutputRole.BODY,
        source_start_ms=4000,
        source_end_ms=9000,
    )
    initial = HighlightSelection(
        OutputCollection(
            "c",
            "a",
            (candidate,),
            (OutputPlan("video-1", "candidate-1", "topic", (body,)),),
        ),
        (),
        (5000,),
    )
    provider = FakeProvider(
        {
            "ranges": [
                {
                    "output_id": "video-1",
                    "start_id": "6",
                    "end_id": "8",
                    "hook_start_id": None,
                    "hook_end_id": None,
                }
            ]
        }
    )
    brief = HighlightBrief.for_preset(
        HighlightPreset.PODCAST,
        boundary_version=version,
        count=1,
        min_ms=1000,
        max_ms=60000,
    )
    result = asyncio.run(
        refine_boundaries(initial, brief, transcript, segments, provider, "fake", 20000)
    )
    assert result.collection is not None
    refined_body = result.collection.plans[0].items[0]
    assert refined_body.segment_id == segments[6].segment_id
    assert refined_body.source_start_ms == 5900
    validate_output_collection(result.collection, segments)


@pytest.mark.parametrize("hook_ms", [None, 5000])
@pytest.mark.parametrize("duration", [60, 200])
def test_compact_context_preserves_text_and_bounds_ids_locally(
    hook_ms: int | None, duration: int
) -> None:
    transcript = Transcript(
        "t",
        TranscriptSource("a", "test", "test"),
        "zh",
        tuple(
            Word(f"w{i}", f"不能{i}。", i * 1000, i * 1000 + 900)
            for i in range(duration)
        ),
    )
    segments = sentence_segments(transcript)
    brief = HighlightBrief.for_preset(
        HighlightPreset.PODCAST,
        count=1,
        min_ms=1000,
        max_ms=duration * 1000,
        hook_ms=hook_ms,
        boundary_version=3,
    )
    initial = select_highlights(
        proposal(tuple(s.segment_id for s in segments[15 : duration - 15])),
        brief,
        segments,
        "a",
        "c",
    )
    assert initial.collection is not None
    compact = build_boundary_request(initial.collection, brief, transcript, "test")
    payload = json.loads(compact.request.user_prompt)
    entry = payload["outputs"][0]
    assert payload["version"] == "boundaries-v3"
    assert (
        "start_ms" not in compact.request.user_prompt
        and "end_ms" not in compact.request.user_prompt
    )
    body = initial.collection.plans[0].items[-1]
    assert body.source_start_ms is not None and body.source_end_ms is not None
    assert all(
        abs(transcript.words[int(row[0])].start_ms - body.source_start_ms) <= 10000
        and len(row) == 2
        for row in entry["start_words"]
    )
    assert all(
        abs(transcript.words[int(row[0])].end_ms - body.source_end_ms) <= 10000
        and len(row) == 2
        for row in entry["end_words"]
    )
    assert "不能" in entry["context"][0][2]
    assert entry["initial_range"] == ["15", str(duration - 16)]
    assert len(entry["context"]) == (1 if duration == 60 else 2)
    if hook_ms is None:
        assert entry["hook_words"] == [] and compact.hooks["video-1"] == set()
    else:
        for identity, text, start, end in entry["hook_words"]:
            original = transcript.words[int(identity)]
            assert (text, start, end) == (
                original.text,
                original.start_ms - body.source_start_ms,
                original.end_ms - body.source_start_ms,
            )
    # The model may return a known word from the wrong edge; it must stay a draft
    # warning and cannot enlarge/shrink the body past the allowed windows.
    response = FakeProvider(
        {
            "ranges": [
                {
                    "output_id": "video-1",
                    "start_id": entry["end_words"][-1][0],
                    "end_id": entry["start_words"][0][0],
                }
            ]
        }
    )
    result = asyncio.run(
        refine_boundaries(
            initial, brief, transcript, segments, response, "test", duration * 1000
        )
    )
    assert result.collection is not None
    assert result.collection.plans[0].items == initial.collection.plans[0].items
    assert any("建议检查" in n for n in result.notes)
