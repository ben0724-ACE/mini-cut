import json
import unittest

from minicut.edit_plan import (
    EditBrief,
    EditIntensity,
    PlannerKind,
    PlanProvenance,
)
from minicut.llm_planner import LLM_POLICY_VERSION, LlmPlanner
from minicut.llm_prompt import EDIT_PLAN_PROMPT_VERSION
from minicut.llm_provider import TextModelRequest, TextModelResponse
from minicut.rule_planner import RULE_POLICY_VERSION, RulePlanner
from minicut.semantic_segment import SegmentLabel, SemanticSegment


def _brief() -> EditBrief:
    return EditBrief(1_000, EditIntensity.BALANCED, "natural")


def _segments() -> tuple[SemanticSegment, ...]:
    return (
        SemanticSegment(
            "segment-1",
            "内容",
            0,
            800,
            ("utterance-1",),
            ("word-1",),
            labels=(SegmentLabel.CONTENT,),
        ),
    )


class CredentialHoldingProvider:
    def __init__(self) -> None:
        self.api_key = "sk-private-value"

    async def generate(self, request: TextModelRequest) -> TextModelResponse:
        del request
        return TextModelResponse(
            json.dumps(
                {
                    "summary": "Keep content.",
                    "decisions": [
                        {
                            "segment_id": "segment-1",
                            "action": "keep",
                            "reason": "content",
                            "confidence": 0.9,
                            "explanation": "Core content.",
                            "labels": ["content"],
                        }
                    ],
                }
            ),
            "provider-resolved-model",
        )


class PlanProvenanceTest(unittest.IsolatedAsyncioTestCase):
    def test_rule_plan_records_no_model_and_rule_policy_version(self) -> None:
        plan = RulePlanner().plan(_brief(), _segments())

        self.assertEqual(
            plan.provenance,
            PlanProvenance(
                PlannerKind.RULE,
                "none",
                "none",
                RULE_POLICY_VERSION,
            ),
        )

    async def test_llm_plan_records_actual_versions_without_credentials(self) -> None:
        provider = CredentialHoldingProvider()

        plan = await LlmPlanner(provider, "requested-model").plan(
            _brief(),
            _segments(),
        )
        serialized = json.dumps(plan.to_dict())

        self.assertEqual(plan.provenance.planner, PlannerKind.LLM)
        self.assertEqual(plan.provenance.model, "provider-resolved-model")
        self.assertEqual(plan.provenance.prompt_version, EDIT_PLAN_PROMPT_VERSION)
        self.assertEqual(plan.provenance.policy_version, LLM_POLICY_VERSION)
        self.assertNotIn(provider.api_key, serialized)
        self.assertNotIn("api_key", serialized)

    def test_provenance_rejects_blank_version_fields(self) -> None:
        invalid_factories = (
            lambda: PlanProvenance(PlannerKind.LLM, "", "prompt-v1", "policy-v1"),
            lambda: PlanProvenance(PlannerKind.LLM, "model", " ", "policy-v1"),
            lambda: PlanProvenance(PlannerKind.LLM, "model", "prompt-v1", ""),
        )

        for factory in invalid_factories:
            with self.subTest(factory=factory):
                with self.assertRaisesRegex(ValueError, "blank"):
                    factory()


if __name__ == "__main__":
    unittest.main()
