import asyncio
import json

from minicut.highlight_brief import HighlightBrief, HighlightPreset
from minicut.highlight_planner import HighlightPlanner
from minicut.highlight_workflow import plan_highlights
from minicut.llm_provider import TextModelRequest, TextModelResponse
from tests.test_highlight_planner import candidate, source


class SequenceProvider:
    def __init__(self, responses: list[object]) -> None:
        self.responses = responses
        self.requests: list[TextModelRequest] = []

    async def generate(self, request: TextModelRequest) -> TextModelResponse:
        self.requests.append(request)
        return TextModelResponse(
            json.dumps(self.responses[len(self.requests) - 1]), request.model
        )


def test_measured_feedback_repairs_once_without_changing_requirements() -> None:
    provider = SequenceProvider(
        [
            {"candidates": [candidate(["a", "b", "c", "d"])], "notes": []},
            {
                "candidates": [candidate(["a", "b"]), candidate(["c", "d"])],
                "notes": ["只有两条"],
            },
        ]
    )
    result = asyncio.run(
        plan_highlights(
            HighlightPlanner(provider),
            HighlightBrief.for_preset(HighlightPreset.KNOWLEDGE),
            source(),
            "asset",
            "selected",
        )
    )
    assert len(provider.requests) == 2
    assert result.selection.collection is not None
    assert len(result.selection.collection.plans) == 2
    feedback = json.loads(provider.requests[1].user_prompt)
    assert "120000" in str(feedback["revision"])
    assert feedback["brief"]["max_ms"] == 90000


def test_second_failure_stops_and_empty_insufficiency_does_not_retry() -> None:
    bad = {"candidates": [candidate(["a", "b", "c", "d"])], "notes": []}
    provider = SequenceProvider([bad, bad])
    result = asyncio.run(
        plan_highlights(
            HighlightPlanner(provider),
            HighlightBrief.for_preset(HighlightPreset.KNOWLEDGE),
            source(),
            "asset",
            "selected",
        )
    )
    assert len(provider.requests) == 2
    assert result.selection.collection is None
    empty = SequenceProvider([{"candidates": [], "notes": ["不足"]}])
    asyncio.run(
        plan_highlights(
            HighlightPlanner(empty),
            HighlightBrief.for_preset(HighlightPreset.KNOWLEDGE),
            source(),
            "asset",
            "selected",
        )
    )
    assert len(empty.requests) == 1


def test_explicit_review_feedback_revises_even_when_duration_passes() -> None:
    data = {"candidates": [candidate(["a", "b"]), candidate(["c", "d"])], "notes": []}
    provider = SequenceProvider([data])
    from minicut.highlight_planner import HighlightProposal, HighlightSuggestion
    from minicut.output_plan import HighlightCandidate

    previous = HighlightProposal(
        (
            HighlightSuggestion(
                HighlightCandidate("c", "没有兑现的标题", "理由", ("a", "b"))
            ),
        ),
        (),
        "fake",
    )
    result = asyncio.run(
        plan_highlights(
            HighlightPlanner(provider),
            HighlightBrief.for_preset(HighlightPreset.KNOWLEDGE, count=1),
            source(),
            "asset",
            "selected",
            previous=previous,
            review_notes=("结尾只有引入，没有解释标题",),
        )
    )
    assert result.revised
    assert len(provider.requests) == 1
    assert "结尾只有引入" in provider.requests[0].user_prompt


def test_punctuation_continuation_keeps_conclusion_without_mutating_source() -> None:
    from minicut.highlight_workflow import attach_continuation_context

    segments = source()
    segments[1].text = "这些对象都是，"
    prepared = attach_continuation_context(segments)
    assert prepared[1].context_dependencies[0].segment_id == "c"
    assert segments[1].context_dependencies == ()
    assert attach_continuation_context(prepared) == prepared
