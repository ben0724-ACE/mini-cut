import asyncio
from dataclasses import replace

from minicut.boundary_refinement import refine_boundaries
from minicut.highlight_brief import HighlightBrief, HighlightPreset
from minicut.highlight_selection import select_highlights
from minicut.sentence_boundaries import sentence_segments
from minicut.transcript import Transcript, TranscriptSource, Word
from tests.test_highlight_planner import FakeProvider
from tests.test_highlight_selection import proposal


def test_semantic_word_ids_refine_unpunctuated_body_without_holes() -> None:
    transcript = Transcript(
        "t",
        TranscriptSource("a", "test", "test"),
        "zh",
        tuple(Word(f"w{i}", "内容", i * 1000, i * 1000 + 900) for i in range(60)),
    )
    segments = sentence_segments(transcript)
    brief = HighlightBrief.for_preset(
        HighlightPreset.PODCAST, count=1, min_ms=10000, max_ms=60000, hook_ms=5000
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
