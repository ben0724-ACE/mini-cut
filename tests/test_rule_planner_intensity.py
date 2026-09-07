import json
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
    label: SegmentLabel,
) -> SemanticSegment:
    return SemanticSegment(
        segment_id=f"segment-{ordinal}",
        text=f"segment text {ordinal}",
        start_ms=ordinal * 1_000,
        end_ms=ordinal * 1_000 + 800,
        utterance_ids=(f"utterance-{ordinal}",),
        word_ids=(f"word-{ordinal}",),
        labels=(label,),
    )


def _segments() -> tuple[SemanticSegment, ...]:
    return (
        _segment(0, SegmentLabel.SILENCE),
        _segment(1, SegmentLabel.FILLER),
        _segment(2, SegmentLabel.FALSE_START),
        _segment(3, SegmentLabel.CONTENT),
        _segment(4, SegmentLabel.REPETITION_CANDIDATE),
    )


class RulePlannerIntensityTest(unittest.TestCase):
    def test_intensity_controls_candidate_deletion(self) -> None:
        expected_actions = {
            EditIntensity.CONSERVATIVE: (
                EditAction.DELETE,
                EditAction.KEEP,
                EditAction.KEEP,
                EditAction.KEEP,
                EditAction.KEEP,
            ),
            EditIntensity.BALANCED: (
                EditAction.DELETE,
                EditAction.DELETE,
                EditAction.KEEP,
                EditAction.KEEP,
                EditAction.KEEP,
            ),
            EditIntensity.AGGRESSIVE: (
                EditAction.DELETE,
                EditAction.DELETE,
                EditAction.DELETE,
                EditAction.KEEP,
                EditAction.DELETE,
            ),
        }

        for intensity, expected in expected_actions.items():
            with self.subTest(intensity=intensity):
                brief = EditBrief(2_000, intensity, "natural")
                plan = RulePlanner().plan(brief, _segments())
                self.assertEqual(
                    tuple(decision.action for decision in plan.decisions),
                    expected,
                )

    def test_aggressive_decisions_have_specific_reasons(self) -> None:
        brief = EditBrief(2_000, EditIntensity.AGGRESSIVE, "natural")

        plan = RulePlanner().plan(brief, _segments())

        self.assertEqual(
            tuple(decision.reason for decision in plan.decisions),
            (
                ReasonCode.SILENCE,
                ReasonCode.FILLER,
                ReasonCode.FALSE_START,
                ReasonCode.CONTENT,
                ReasonCode.REPETITION,
            ),
        )

    def test_must_keep_overrides_every_intensity(self) -> None:
        segments = (_segment(0, SegmentLabel.REPETITION_CANDIDATE),)

        for intensity in EditIntensity:
            with self.subTest(intensity=intensity):
                brief = EditBrief(
                    1_000,
                    intensity,
                    "natural",
                    must_keep=(ContentRequirement("保留强调重复", ("segment-0",)),),
                )
                plan = RulePlanner().plan(brief, segments)
                self.assertEqual(plan.decisions[0].action, EditAction.KEEP)
                self.assertEqual(
                    plan.decisions[0].reason,
                    ReasonCode.USER_REQUIRED,
                )

    def test_same_input_produces_byte_stable_plan(self) -> None:
        brief = EditBrief(2_000, EditIntensity.AGGRESSIVE, "natural")
        planner = RulePlanner()

        first = json.dumps(
            planner.plan(brief, _segments()).to_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
        second = json.dumps(
            planner.plan(brief, _segments()).to_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()

        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
