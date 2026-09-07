import unittest

from minicut.edit_plan import (
    ContentRequirement,
    EditAction,
    EditBrief,
    EditIntensity,
    ReasonCode,
)
from minicut.rule_planner import RulePlanner
from minicut.semantic_segment import SegmentLabel, SemanticSegment


def _segment(
    ordinal: int,
    text: str,
    labels: tuple[SegmentLabel, ...],
) -> SemanticSegment:
    return SemanticSegment(
        segment_id=f"segment-{ordinal}",
        text=text,
        start_ms=ordinal * 1_000,
        end_ms=ordinal * 1_000 + 800,
        utterance_ids=(f"utterance-{ordinal}",),
        word_ids=(f"word-{ordinal}",),
        labels=labels,
    )


class RulePlannerSilenceTest(unittest.TestCase):
    def test_explicit_silence_is_deleted_and_content_is_kept(self) -> None:
        segments = (
            _segment(0, "开场内容", (SegmentLabel.CONTENT,)),
            _segment(1, "[静音]", (SegmentLabel.SILENCE,)),
            _segment(2, "silence", (SegmentLabel.CONTENT,)),
        )
        brief = EditBrief(2_000, EditIntensity.BALANCED, "natural")

        plan = RulePlanner().plan(brief, segments)

        self.assertEqual(
            tuple((decision.action, decision.reason) for decision in plan.decisions),
            (
                (EditAction.KEEP, ReasonCode.CONTENT),
                (EditAction.DELETE, ReasonCode.SILENCE),
                (EditAction.KEEP, ReasonCode.CONTENT),
            ),
        )

    def test_must_keep_overrides_silence_deletion(self) -> None:
        segments = (_segment(0, "[静音]", (SegmentLabel.SILENCE,)),)
        brief = EditBrief(
            1_000,
            EditIntensity.BALANCED,
            "natural",
            must_keep=(ContentRequirement("保留此停顿", ("segment-0",)),),
        )

        plan = RulePlanner().plan(brief, segments)

        self.assertEqual(plan.decisions[0].action, EditAction.KEEP)
        self.assertEqual(plan.decisions[0].reason, ReasonCode.USER_REQUIRED)


if __name__ == "__main__":
    unittest.main()
