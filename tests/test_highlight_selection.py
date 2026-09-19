from dataclasses import replace

from minicut.highlight_brief import HighlightBrief, HighlightPreset
from minicut.highlight_planner import HighlightProposal, HighlightSuggestion
from minicut.highlight_selection import select_highlights, source_overlap
from minicut.output_plan import HighlightCandidate
from minicut.semantic_segment import ContextDirection, SegmentContextDependency
from tests.test_highlight_planner import source


def proposal(*ids: tuple[str, ...]) -> HighlightProposal:
    return HighlightProposal(
        tuple(
            HighlightSuggestion(
                HighlightCandidate(f"c-{i}", "标题不是旁白", "理由", group)
            )
            for i, group in enumerate(ids)
        ),
        (),
        "fake",
    )


def test_diversity_duration_and_shortage() -> None:
    brief = HighlightBrief.for_preset(HighlightPreset.KNOWLEDGE)
    result = select_highlights(
        proposal(("a", "b"), ("b", "c"), ("c", "d"), ("a",)),
        brief,
        source(),
        "asset",
        "selected",
    )
    assert result.collection is not None
    assert len(result.collection.plans) == 2
    assert any("重复" in n for n in result.notes)
    assert any("不足" in n for n in result.notes)
    assert source_overlap(((0, 60000),), ((30000, 90000),)) == 0.5


def test_context_expansion_and_overlong_explanation() -> None:
    segments = source()
    segments[1].context_dependencies = (
        SegmentContextDependency("a", ContextDirection.PRECEDING),
    )
    brief = HighlightBrief.for_preset(HighlightPreset.KNOWLEDGE)
    result = select_highlights(
        proposal(("b", "c")), brief, segments, "asset", "selected"
    )
    assert result.collection is not None
    assert len(result.collection.plans[0].items) == 1
    assert result.collection.plans[0].items[0].source_end_ms == 90000
    rejected = select_highlights(
        proposal(("b", "c")),
        replace(brief, max_ms=60000),
        segments,
        "asset",
        "selected",
    )
    assert rejected.collection is None
    assert any("超限" in n for n in rejected.notes)


def test_hook_reuse_not_counted_twice_in_diversity_and_whole_quote() -> None:
    brief = HighlightBrief.for_preset(
        HighlightPreset.OPINION, min_ms=30000, max_ms=90000, hook_ms=5000
    )
    p = proposal(("a", "b"))
    p = replace(p, suggestions=(replace(p.suggestions[0], hook_segment_ids=("b",)),))
    result = select_highlights(p, brief, source(), "asset", "selected")
    assert result.collection is not None
    assert len(result.collection.plans[0].items) == 1
    assert result.durations_ms == (60000,)
    assert any("钩子" in n for n in result.notes)


def test_continuous_body_keeps_omitted_middle_and_pauses() -> None:
    brief = HighlightBrief.for_preset(
        HighlightPreset.KNOWLEDGE, min_ms=None, max_ms=None, count=1
    )
    segments = source()
    result = select_highlights(
        proposal(("a", "c")), brief, segments, "asset", "continuous"
    )
    assert result.collection is not None
    item = result.collection.plans[0].items[0]
    assert (item.source_start_ms, item.source_end_ms) == (0, 90000)
    assert "b" in result.collection.candidates[0].context_segment_ids
    compact = select_highlights(
        proposal(("a", "c")),
        replace(brief, body_mode="compact"),
        segments,
        "asset",
        "compact",
    )
    assert compact.collection is not None
    assert [i.segment_id for i in compact.collection.plans[0].items] == ["a", "c"]


def test_soft_duration_limit_keeps_complete_short_and_slightly_long_content() -> None:
    brief = HighlightBrief.for_preset(
        HighlightPreset.KNOWLEDGE, count=1, min_ms=45000, max_ms=55000
    )
    assert (
        select_highlights(proposal(("a",)), brief, source(), "a", "short").collection
        is not None
    )
    assert (
        select_highlights(proposal(("a", "b")), brief, source(), "a", "long").collection
        is not None
    )
    assert (
        select_highlights(
            proposal(("a", "c")), brief, source(), "a", "too-long"
        ).collection
        is None
    )
