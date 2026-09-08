import unittest

from minicut.edit_plan import ContentRequirement, EditBrief, EditIntensity
from minicut.local_analysis import LocalSegmentAnalysis, SegmentClassification
from minicut.narrative_outline import NarrativeOutline, NarrativeSection
from minicut.narrative_selection import (
    DurationFallback,
    select_for_target_duration,
    select_narrative_candidates,
)
from minicut.semantic_segment import SemanticSegment


def _segment(ordinal: int, duration_ms: int = 1_000) -> SemanticSegment:
    start_ms = ordinal * 2_000
    return SemanticSegment(
        segment_id=f"segment-{ordinal}",
        text=f"内容 {ordinal}",
        start_ms=start_ms,
        end_ms=start_ms + duration_ms,
        utterance_ids=(f"utterance-{ordinal}",),
        word_ids=(f"word-{ordinal}",),
    )


def _analysis(
    ordinal: int,
    importance: float = 0.8,
    dependencies: tuple[str, ...] = (),
) -> LocalSegmentAnalysis:
    return LocalSegmentAnalysis(
        f"segment-{ordinal}",
        SegmentClassification.CONTENT,
        importance,
        dependencies,
        f"理由 {ordinal}",
        False,
    )


def _outline(
    core_ids: tuple[str, ...] = ("segment-1", "segment-2"),
) -> NarrativeOutline:
    return NarrativeOutline(
        "主题",
        NarrativeSection("开场", ("segment-0",)),
        (NarrativeSection("观点", core_ids),),
        NarrativeSection("结论", ("segment-3",)),
    )


class TargetDurationSelectionTest(unittest.TestCase):
    def test_adds_optional_evidence_to_reach_ten_percent_tolerance(self) -> None:
        segments = tuple(_segment(index) for index in range(4))
        analyses = tuple(_analysis(index, 0.9 - index * 0.1) for index in range(4))
        brief = EditBrief(4_000, EditIntensity.BALANCED, "自然")
        candidates = select_narrative_candidates(brief, segments, analyses, _outline())

        result = select_for_target_duration(brief, segments, candidates)

        self.assertEqual(
            result.selected_ids,
            ("segment-0", "segment-1", "segment-2", "segment-3"),
        )
        self.assertEqual(result.estimated_duration_ms, 4_000)
        self.assertTrue(result.tolerance_met)
        self.assertEqual(result.fallback, DurationFallback.NONE)
        self.assertEqual(
            select_for_target_duration(brief, segments, candidates), result
        )

    def test_selected_root_always_brings_its_dependency(self) -> None:
        segments = tuple(_segment(index) for index in range(5))
        analyses = (
            _analysis(0),
            _analysis(1, dependencies=("segment-4",)),
            _analysis(2),
            _analysis(3),
            _analysis(4),
        )
        brief = EditBrief(4_000, EditIntensity.BALANCED, "自然")
        candidates = select_narrative_candidates(
            brief,
            segments,
            analyses,
            _outline(("segment-1",)),
        )

        result = select_for_target_duration(brief, segments, candidates)

        self.assertEqual(
            result.selected_ids,
            ("segment-0", "segment-1", "segment-3", "segment-4"),
        )
        self.assertTrue(result.tolerance_met)

    def test_preserves_required_content_when_it_exceeds_target(self) -> None:
        segments = tuple(_segment(index) for index in range(4))
        analyses = tuple(_analysis(index) for index in range(4))
        brief = EditBrief(
            2_000,
            EditIntensity.BALANCED,
            "自然",
            must_keep=(
                ContentRequirement(
                    "全部保留",
                    tuple(segment.segment_id for segment in segments),
                ),
            ),
        )
        candidates = select_narrative_candidates(brief, segments, analyses, _outline())

        result = select_for_target_duration(brief, segments, candidates)

        self.assertEqual(result.selected_ids, candidates.required_ids)
        self.assertEqual(result.estimated_duration_ms, 4_000)
        self.assertFalse(result.tolerance_met)
        self.assertEqual(result.fallback, DurationFallback.REQUIRED_OVERFLOW)
        self.assertIn("must-keep", result.explanation)

    def test_returns_explained_closest_complete_result_when_target_is_unreachable(
        self,
    ) -> None:
        segments = (_segment(0), _segment(1), _segment(3))
        analyses = (_analysis(0), _analysis(1), _analysis(3))
        outline = _outline(("segment-1",))
        brief = EditBrief(5_000, EditIntensity.BALANCED, "自然")
        candidates = select_narrative_candidates(brief, segments, analyses, outline)

        result = select_for_target_duration(brief, segments, candidates)

        self.assertEqual(result.estimated_duration_ms, 3_000)
        self.assertFalse(result.tolerance_met)
        self.assertEqual(result.fallback, DurationFallback.CLOSEST_COMPLETE)
        self.assertIn("complete narrative", result.explanation)


if __name__ == "__main__":
    unittest.main()
