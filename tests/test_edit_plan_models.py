import json
import unittest
from collections.abc import Callable

from minicut.edit_plan import (
    EDIT_PLAN_SCHEMA_VERSION,
    EditAction,
    EditBrief,
    EditDecision,
    EditIntensity,
    EditPlan,
    PlannerKind,
    PlanProvenance,
    ReasonCode,
)


def _brief() -> EditBrief:
    return EditBrief(60_000, EditIntensity.BALANCED, "natural")


def _provenance() -> PlanProvenance:
    return PlanProvenance(PlannerKind.RULE, "none", "none", "test-policy-v1")


class EditDecisionTest(unittest.TestCase):
    def test_decision_round_trips_structured_reason_and_labels(self) -> None:
        decision = EditDecision(
            segment_id="segment-1",
            action=EditAction.DELETE,
            reason=ReasonCode.FILLER,
            confidence=0.95,
            explanation="Pure filler with no content",
            labels=("rule", "speech"),
        )

        restored = EditDecision.from_dict(
            json.loads(json.dumps(decision.to_dict(), ensure_ascii=False))
        )

        self.assertEqual(restored, decision)
        self.assertNotIn("start_ms", decision.to_dict())
        self.assertNotIn("end_ms", decision.to_dict())

    def test_decision_rejects_invalid_local_fields(self) -> None:
        invalid_factories: tuple[Callable[[], EditDecision], ...] = (
            lambda: EditDecision(
                "", EditAction.KEEP, ReasonCode.CONTENT, 1.0, "Keep content"
            ),
            lambda: EditDecision(
                "segment-1", EditAction.KEEP, ReasonCode.CONTENT, -0.01, "Keep"
            ),
            lambda: EditDecision(
                "segment-1", EditAction.KEEP, ReasonCode.CONTENT, 1.01, "Keep"
            ),
            lambda: EditDecision(
                "segment-1", EditAction.KEEP, ReasonCode.CONTENT, 1.0, " "
            ),
            lambda: EditDecision(
                "segment-1",
                EditAction.KEEP,
                ReasonCode.CONTENT,
                1.0,
                "Keep",
                ("duplicate", "duplicate"),
            ),
        )

        for index, create_decision in enumerate(invalid_factories):
            with self.subTest(index=index):
                with self.assertRaises(ValueError):
                    create_decision()


class EditPlanModelTest(unittest.TestCase):
    def test_plan_round_trips_brief_decisions_summary_and_version(self) -> None:
        plan = EditPlan(
            brief=_brief(),
            decisions=(
                EditDecision(
                    "segment-1",
                    EditAction.KEEP,
                    ReasonCode.CONTENT,
                    0.9,
                    "Core explanation",
                ),
            ),
            summary="Keep the core explanation.",
            provenance=_provenance(),
        )

        restored = EditPlan.from_dict(
            json.loads(json.dumps(plan.to_dict(), ensure_ascii=False))
        )

        self.assertEqual(restored, plan)
        self.assertEqual(restored.schema_version, EDIT_PLAN_SCHEMA_VERSION)

    def test_plan_allows_empty_decisions_until_integrity_validation(self) -> None:
        plan = EditPlan(_brief(), (), "No decisions yet", _provenance())

        self.assertEqual(plan.decisions, ())

    def test_plan_rejects_blank_summary(self) -> None:
        with self.assertRaisesRegex(ValueError, "summary"):
            EditPlan(_brief(), (), " ", _provenance())


if __name__ == "__main__":
    unittest.main()
