import unittest

from minicut.edit_plan import (
    EditAction,
    EditBrief,
    EditDecision,
    EditIntensity,
    EditPlan,
    PlannerKind,
    PlanProvenance,
    ReasonCode,
)
from minicut.media import TimeRange
from minicut.semantic_segment import SemanticSegment
from minicut.timeline import compile_timeline, resolve_kept_segments


def _segment(ordinal: int) -> SemanticSegment:
    return SemanticSegment(
        segment_id=f"segment-{ordinal}",
        text=f"内容 {ordinal}",
        start_ms=ordinal * 1_000,
        end_ms=ordinal * 1_000 + 800,
        utterance_ids=(f"utterance-{ordinal}",),
        word_ids=(f"word-{ordinal}",),
    )


def _decision(segment_id: str, action: EditAction) -> EditDecision:
    return EditDecision(
        segment_id,
        action,
        ReasonCode.CONTENT,
        0.8,
        "测试决定。",
    )


def _plan(decisions: tuple[EditDecision, ...]) -> EditPlan:
    return EditPlan(
        EditBrief(2_000, EditIntensity.BALANCED, "自然"),
        decisions,
        "测试计划。",
        PlanProvenance(PlannerKind.RULE, "none", "none", "test-v1"),
    )


class ResolveKeptSegmentsTest(unittest.TestCase):
    def test_resolves_keep_decisions_in_source_time_order(self) -> None:
        segments = (_segment(2), _segment(0), _segment(1))
        plan = _plan(
            (
                _decision("segment-1", EditAction.DELETE),
                _decision("segment-2", EditAction.KEEP),
                _decision("segment-0", EditAction.KEEP),
            )
        )

        kept = resolve_kept_segments(plan, segments)

        self.assertEqual(
            tuple(segment.segment_id for segment in kept),
            ("segment-0", "segment-2"),
        )

    def test_rejects_a_valid_plan_with_no_kept_segments(self) -> None:
        segments = (_segment(0), _segment(1))
        plan = _plan(
            tuple(
                _decision(segment.segment_id, EditAction.DELETE) for segment in segments
            )
        )

        with self.assertRaisesRegex(ValueError, "no kept Segments"):
            resolve_kept_segments(plan, segments)

    def test_reuses_edit_plan_integrity_validation(self) -> None:
        segments = (_segment(0), _segment(1))
        plan = _plan((_decision("segment-0", EditAction.KEEP),))

        with self.assertRaisesRegex(ValueError, "missing"):
            resolve_kept_segments(plan, segments)


class CompileTimelineTest(unittest.TestCase):
    def test_compiles_contiguous_output_ranges_and_exact_total_duration(self) -> None:
        segment_0 = _segment(0)
        segment_1 = SemanticSegment(
            segment_id="segment-1",
            text="较长内容",
            start_ms=2_000,
            end_ms=3_500,
            utterance_ids=("utterance-1",),
            word_ids=("word-1",),
        )
        segment_2 = SemanticSegment(
            segment_id="segment-2",
            text="结尾内容",
            start_ms=4_000,
            end_ms=4_800,
            utterance_ids=("utterance-2",),
            word_ids=("word-2",),
        )
        segments = (segment_2, segment_1, segment_0)
        plan = _plan(
            (
                _decision("segment-2", EditAction.KEEP),
                _decision("segment-0", EditAction.KEEP),
                _decision("segment-1", EditAction.KEEP),
            )
        )

        timeline = compile_timeline(plan, segments, "asset-1")

        self.assertEqual(
            tuple(clip.segment_id for clip in timeline.clips),
            ("segment-0", "segment-1", "segment-2"),
        )
        self.assertEqual(
            tuple(clip.source_range for clip in timeline.clips),
            (TimeRange(0, 800), TimeRange(2_000, 3_500), TimeRange(4_000, 4_800)),
        )
        self.assertEqual(
            tuple(clip.output_range for clip in timeline.clips),
            (TimeRange(0, 800), TimeRange(800, 2_300), TimeRange(2_300, 3_100)),
        )
        self.assertEqual(timeline.estimated_duration_ms, 3_100)
        self.assertEqual(compile_timeline(plan, segments, "asset-1"), timeline)

    def test_rejects_blank_source_asset_id(self) -> None:
        segments = (_segment(0),)
        plan = _plan((_decision("segment-0", EditAction.KEEP),))

        with self.assertRaisesRegex(ValueError, "asset"):
            compile_timeline(plan, segments, " ")


if __name__ == "__main__":
    unittest.main()
