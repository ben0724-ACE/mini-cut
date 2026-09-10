import json
import unittest

from minicut.edit_plan import EditBrief, EditIntensity
from minicut.llm_prompt import EDIT_PLAN_PROMPT_VERSION, build_edit_plan_request
from minicut.semantic_segment import (
    ContextDirection,
    SegmentContextDependency,
    SegmentLabel,
    SemanticSegment,
)


def _segments() -> tuple[SemanticSegment, ...]:
    return (
        SemanticSegment(
            "segment-1",
            "开场",
            100,
            900,
            ("utterance-1",),
            ("word-1",),
            labels=(SegmentLabel.CONTENT,),
        ),
        SemanticSegment(
            "segment-2",
            "嗯",
            1_000,
            1_200,
            ("utterance-2",),
            ("word-2",),
            context_dependencies=(
                SegmentContextDependency(
                    "segment-1",
                    ContextDirection.PRECEDING,
                ),
            ),
            labels=(SegmentLabel.FILLER,),
        ),
    )


class EditPlanPromptTest(unittest.TestCase):
    def test_request_exposes_only_stable_editing_context(self) -> None:
        brief = EditBrief(1_000, EditIntensity.BALANCED, "concise")

        request = build_edit_plan_request(brief, _segments(), "local-model")
        payload = json.loads(request.user_prompt)

        self.assertEqual(request.model, "local-model")
        self.assertEqual(payload["prompt_version"], EDIT_PLAN_PROMPT_VERSION)
        self.assertEqual(
            payload["allowed_segment_ids"],
            ["segment-1", "segment-2"],
        )
        self.assertEqual(
            payload["segments"],
            [
                {
                    "segment_id": "segment-1",
                    "text": "开场",
                    "labels": ["content"],
                    "context_segment_ids": [],
                },
                {
                    "segment_id": "segment-2",
                    "text": "嗯",
                    "labels": ["filler"],
                    "context_segment_ids": ["segment-1"],
                },
            ],
        )
        serialized = request.system_prompt + request.user_prompt
        for forbidden in ("start_ms", "end_ms", "word-1", "utterance-1", "api_key"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, serialized)

    def test_prompt_limits_actions_reasons_and_segment_references(self) -> None:
        brief = EditBrief(1_000, EditIntensity.CONSERVATIVE, "natural")

        first = build_edit_plan_request(brief, _segments(), "model")
        second = build_edit_plan_request(brief, _segments(), "model")

        self.assertEqual(first, second)
        self.assertIn("allowed_segment_ids", first.system_prompt)
        self.assertIn("exactly one decision", first.system_prompt)
        self.assertIn("keep", first.system_prompt)
        self.assertIn("delete", first.system_prompt)
        self.assertIn("JSON", first.system_prompt)
        self.assertNotIn("user_removed", first.system_prompt)


if __name__ == "__main__":
    unittest.main()
