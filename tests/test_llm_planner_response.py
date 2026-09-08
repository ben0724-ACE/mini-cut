import json
import unittest

from minicut.edit_plan import EditAction, EditBrief, EditIntensity
from minicut.llm_planner import InvalidModelResponseError, LlmPlanner
from minicut.llm_provider import TextModelRequest, TextModelResponse
from minicut.semantic_segment import SegmentLabel, SemanticSegment


def _segments() -> tuple[SemanticSegment, ...]:
    return (
        SemanticSegment(
            "segment-1",
            "核心内容",
            0,
            800,
            ("utterance-1",),
            ("word-1",),
            labels=(SegmentLabel.CONTENT,),
        ),
        SemanticSegment(
            "segment-2",
            "嗯",
            900,
            1_100,
            ("utterance-2",),
            ("word-2",),
            labels=(SegmentLabel.FILLER,),
        ),
    )


def _brief() -> EditBrief:
    return EditBrief(900, EditIntensity.BALANCED, "concise")


def _valid_response() -> str:
    return json.dumps(
        {
            "summary": "Keep the core and remove filler.",
            "decisions": [
                {
                    "segment_id": "segment-1",
                    "action": "keep",
                    "reason": "content",
                    "confidence": 0.95,
                    "explanation": "Core content.",
                    "labels": ["content"],
                },
                {
                    "segment_id": "segment-2",
                    "action": "delete",
                    "reason": "filler",
                    "confidence": 0.9,
                    "explanation": "Pure filler.",
                    "labels": ["filler"],
                },
            ],
        }
    )


class ScriptedProvider:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.requests: list[TextModelRequest] = []

    async def generate(self, request: TextModelRequest) -> TextModelResponse:
        self.requests.append(request)
        return TextModelResponse(self.responses.pop(0), request.model)


class LlmPlannerResponseTest(unittest.IsolatedAsyncioTestCase):
    async def test_valid_structured_response_produces_valid_plan(self) -> None:
        provider = ScriptedProvider([_valid_response()])

        plan = await LlmPlanner(provider, "local-model").plan(_brief(), _segments())

        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(
            tuple(decision.action for decision in plan.decisions),
            (EditAction.KEEP, EditAction.DELETE),
        )

    async def test_invalid_responses_receive_one_controlled_repair(self) -> None:
        unknown_id = json.loads(_valid_response())
        unknown_id["decisions"][1]["segment_id"] = "invented-segment"
        missing_field = json.loads(_valid_response())
        del missing_field["decisions"][0]["action"]
        extra_timestamp = json.loads(_valid_response())
        extra_timestamp["decisions"][0]["start_ms"] = 0
        invalid_responses = (
            "not json",
            json.dumps(unknown_id),
            json.dumps(missing_field),
            json.dumps(extra_timestamp),
        )

        for invalid in invalid_responses:
            with self.subTest(invalid=invalid):
                provider = ScriptedProvider([invalid, _valid_response()])
                plan = await LlmPlanner(provider, "model").plan(
                    _brief(),
                    _segments(),
                )
                self.assertEqual(len(provider.requests), 2)
                self.assertIn("repair", provider.requests[1].system_prompt.casefold())
                self.assertEqual(len(plan.decisions), 2)

    async def test_second_invalid_response_fails_without_a_plan(self) -> None:
        provider = ScriptedProvider(["invalid", '{"summary":"still invalid"}'])

        with self.assertRaisesRegex(InvalidModelResponseError, "repair attempt"):
            await LlmPlanner(provider, "model").plan(_brief(), _segments())

        self.assertEqual(len(provider.requests), 2)


if __name__ == "__main__":
    unittest.main()
