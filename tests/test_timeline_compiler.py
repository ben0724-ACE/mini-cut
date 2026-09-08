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
from minicut.semantic_segment import SemanticSegment
from minicut.timeline import resolve_kept_segments


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


if __name__ == "__main__":
    unittest.main()
