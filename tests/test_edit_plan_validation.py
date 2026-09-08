import json
import unittest
from dataclasses import replace

from minicut.edit_plan import (
    ContentRequirement,
    EditAction,
    EditBrief,
    EditDecision,
    EditIntensity,
    EditPlan,
    PlannerKind,
    PlanProvenance,
    ReasonCode,
    validate_edit_plan,
)
from minicut.semantic_segment import (
    ContextDirection,
    SegmentContextDependency,
    SemanticSegment,
)


def _segments() -> tuple[SemanticSegment, ...]:
    return (
        SemanticSegment(
            "segment-1",
            "开场",
            0,
            1_000,
            ("utterance-1",),
            ("word-1",),
        ),
        SemanticSegment(
            "segment-2",
            "核心内容",
            1_100,
            2_000,
            ("utterance-2",),
            ("word-2",),
            (
                SegmentContextDependency(
                    "segment-1",
                    ContextDirection.PRECEDING,
                ),
            ),
        ),
        SemanticSegment(
            "segment-3",
            "嗯。",
            2_100,
            2_500,
            ("utterance-3",),
            ("word-3",),
        ),
    )


def _decision(segment_id: str, action: EditAction) -> EditDecision:
    return EditDecision(
        segment_id,
        action,
        ReasonCode.CONTENT if action is EditAction.KEEP else ReasonCode.FILLER,
        0.9,
        "Rule-backed decision",
    )


def _brief() -> EditBrief:
    return EditBrief(
        2_000,
        EditIntensity.BALANCED,
        "natural",
        must_keep=(ContentRequirement("保留开场", ("segment-1",)),),
        must_remove=(ContentRequirement("删除口头语", ("segment-3",)),),
    )


def _provenance() -> PlanProvenance:
    return PlanProvenance(PlannerKind.RULE, "none", "none", "test-policy-v1")


def _valid_plan() -> EditPlan:
    return EditPlan(
        _brief(),
        (
            _decision("segment-1", EditAction.KEEP),
            _decision("segment-2", EditAction.KEEP),
            _decision("segment-3", EditAction.DELETE),
        ),
        "Keep the opening and core content.",
        _provenance(),
    )


class EditPlanValidationTest(unittest.TestCase):
    def test_complete_plan_with_satisfied_constraints_is_valid(self) -> None:
        validate_edit_plan(_valid_plan(), _segments())

    def test_unknown_duplicate_and_missing_decision_ids_are_rejected(self) -> None:
        valid = _valid_plan()
        invalid_cases = (
            (
                "unknown",
                replace(
                    valid,
                    decisions=valid.decisions
                    + (_decision("segment-unknown", EditAction.DELETE),),
                ),
            ),
            (
                "duplicate",
                replace(valid, decisions=valid.decisions + (valid.decisions[0],)),
            ),
            ("missing", replace(valid, decisions=valid.decisions[:-1])),
        )

        for message, plan in invalid_cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    validate_edit_plan(plan, _segments())

    def test_unknown_requirement_segment_id_is_rejected(self) -> None:
        brief = replace(
            _brief(),
            must_keep=(ContentRequirement("保留未知内容", ("missing",)),),
        )

        with self.assertRaisesRegex(ValueError, "unknown"):
            validate_edit_plan(replace(_valid_plan(), brief=brief), _segments())

    def test_keep_and_remove_requirements_cannot_conflict(self) -> None:
        brief = replace(
            _brief(),
            must_remove=(ContentRequirement("删除开场", ("segment-1",)),),
        )

        with self.assertRaisesRegex(ValueError, "conflict"):
            validate_edit_plan(replace(_valid_plan(), brief=brief), _segments())

    def test_requirement_actions_must_be_satisfied(self) -> None:
        valid = _valid_plan()
        invalid_cases = (
            (
                "must_keep",
                replace(
                    valid,
                    decisions=(
                        _decision("segment-1", EditAction.DELETE),
                        *valid.decisions[1:],
                    ),
                ),
            ),
            (
                "must_remove",
                replace(
                    valid,
                    decisions=(
                        *valid.decisions[:2],
                        _decision("segment-3", EditAction.KEEP),
                    ),
                ),
            ),
        )

        for message, plan in invalid_cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    validate_edit_plan(plan, _segments())

    def test_kept_segment_cannot_depend_on_a_deleted_segment(self) -> None:
        brief = EditBrief(2_000, EditIntensity.BALANCED, "natural")
        plan = EditPlan(
            brief,
            (
                _decision("segment-1", EditAction.DELETE),
                _decision("segment-2", EditAction.KEEP),
                _decision("segment-3", EditAction.DELETE),
            ),
            "Invalid dependency",
            _provenance(),
        )

        with self.assertRaisesRegex(ValueError, "dependency"):
            validate_edit_plan(plan, _segments())

    def test_schema_version_and_unknown_action_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "schema version"):
            replace(_valid_plan(), schema_version=2)

        invalid_decision = _valid_plan().decisions[0].to_dict()
        invalid_decision["action"] = "trim"
        with self.assertRaisesRegex(ValueError, "trim"):
            EditDecision.from_dict(invalid_decision)

    def test_serialized_plan_has_no_model_controlled_source_timestamps(self) -> None:
        serialized = json.dumps(_valid_plan().to_dict())

        self.assertNotIn('"start_ms"', serialized)
        self.assertNotIn('"end_ms"', serialized)


if __name__ == "__main__":
    unittest.main()
