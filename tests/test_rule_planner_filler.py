import unittest

from minicut.edit_plan import EditAction, EditBrief, EditIntensity, ReasonCode
from minicut.rule_planner import RulePlanner
from minicut.semantic_segment import (
    ContextDirection,
    SegmentContextDependency,
    SegmentLabel,
    SemanticSegment,
)


def _segment(
    ordinal: int,
    text: str,
    labels: tuple[SegmentLabel, ...],
    dependencies: tuple[SegmentContextDependency, ...] = (),
) -> SemanticSegment:
    return SemanticSegment(
        segment_id=f"segment-{ordinal}",
        text=text,
        start_ms=ordinal * 1_000,
        end_ms=ordinal * 1_000 + 800,
        utterance_ids=(f"utterance-{ordinal}",),
        word_ids=(f"word-{ordinal}",),
        context_dependencies=dependencies,
        labels=labels,
    )


def _brief() -> EditBrief:
    return EditBrief(2_000, EditIntensity.BALANCED, "natural")


class RulePlannerFillerTest(unittest.TestCase):
    def test_pure_filler_label_is_deleted_with_filler_reason(self) -> None:
        segments = (
            _segment(0, "嗯", (SegmentLabel.FILLER,)),
            _segment(1, "核心内容", (SegmentLabel.CONTENT,)),
        )

        plan = RulePlanner().plan(_brief(), segments)

        self.assertEqual(plan.decisions[0].action, EditAction.DELETE)
        self.assertEqual(plan.decisions[0].reason, ReasonCode.FILLER)
        self.assertEqual(plan.decisions[1].action, EditAction.KEEP)

    def test_content_containing_filler_word_is_not_deleted(self) -> None:
        segments = (_segment(0, "那个方案就是这样", (SegmentLabel.CONTENT,)),)

        plan = RulePlanner().plan(_brief(), segments)

        self.assertEqual(plan.decisions[0].action, EditAction.KEEP)
        self.assertEqual(plan.decisions[0].reason, ReasonCode.CONTENT)

    def test_filler_required_by_kept_context_is_not_deleted(self) -> None:
        segments = (
            _segment(0, "嗯", (SegmentLabel.FILLER,)),
            _segment(
                1,
                "接下来是结论",
                (SegmentLabel.CONTENT,),
                (
                    SegmentContextDependency(
                        "segment-0",
                        ContextDirection.PRECEDING,
                    ),
                ),
            ),
        )

        plan = RulePlanner().plan(_brief(), segments)

        self.assertEqual(plan.decisions[0].action, EditAction.KEEP)
        self.assertEqual(plan.decisions[1].action, EditAction.KEEP)


if __name__ == "__main__":
    unittest.main()
