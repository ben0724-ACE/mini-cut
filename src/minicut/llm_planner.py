"""LLM-backed structured edit planning with one controlled repair."""

import json
from typing import cast

from minicut.edit_plan import EditBrief, EditDecision, EditPlan, validate_edit_plan
from minicut.errors import ProcessingError
from minicut.llm_prompt import build_edit_plan_request
from minicut.llm_provider import (
    TextModelProvider,
    TextModelRequest,
    TextModelResponse,
)
from minicut.semantic_segment import SemanticSegment

_ROOT_FIELDS = {"summary", "decisions"}
_DECISION_FIELDS = {
    "segment_id",
    "action",
    "reason",
    "confidence",
    "explanation",
    "labels",
}


class InvalidModelResponseError(ProcessingError):
    """Raised when model output cannot become a validated EditPlan."""


def parse_edit_plan_response(content: str, brief: EditBrief) -> EditPlan:
    """Strictly parse the model-owned portion of an EditPlan."""
    try:
        loaded: object = json.loads(content)
        if not isinstance(loaded, dict):
            raise TypeError("response root must be an object")
        root = cast(dict[str, object], loaded)
        if set(root) != _ROOT_FIELDS:
            raise ValueError("response root fields are invalid")

        summary = root["summary"]
        raw_decisions = root["decisions"]
        if not isinstance(summary, str) or not isinstance(raw_decisions, list):
            raise TypeError("response summary or decisions has an invalid type")

        decisions: list[EditDecision] = []
        for raw_decision in cast(list[object], raw_decisions):
            if not isinstance(raw_decision, dict):
                raise TypeError("decision must be an object")
            decision = cast(dict[str, object], raw_decision)
            if set(decision) != _DECISION_FIELDS:
                raise ValueError("decision fields are invalid")
            decisions.append(EditDecision.from_dict(decision))
        return EditPlan(brief, tuple(decisions), summary)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise InvalidModelResponseError(
            "Text model returned an invalid edit plan."
        ) from error


def _validated_plan(
    response: TextModelResponse,
    brief: EditBrief,
    segments: tuple[SemanticSegment, ...],
) -> EditPlan:
    plan = parse_edit_plan_response(response.content, brief)
    try:
        validate_edit_plan(plan, segments)
    except ValueError as error:
        raise InvalidModelResponseError(
            "Text model returned an invalid edit plan."
        ) from error
    return plan


def _build_repair_request(
    request: TextModelRequest,
    invalid_response: str,
) -> TextModelRequest:
    repair_payload = {
        "original_input": json.loads(request.user_prompt),
        "invalid_response": invalid_response,
        "repair_instruction": (
            "Correct the response to satisfy every original constraint."
        ),
    }
    return TextModelRequest(
        model=request.model,
        system_prompt=(
            request.system_prompt
            + " This is the single allowed repair attempt. Return corrected JSON only."
        ),
        user_prompt=json.dumps(
            repair_payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    )


class LlmPlanner:
    """Generate and validate an EditPlan through a text-model provider."""

    def __init__(self, provider: TextModelProvider, model: str) -> None:
        if not model.strip():
            raise ValueError("planner model must not be blank")
        self._provider = provider
        self._model = model

    async def plan(
        self,
        brief: EditBrief,
        segments: tuple[SemanticSegment, ...],
    ) -> EditPlan:
        """Generate a plan, allowing exactly one repair of invalid output."""
        request = build_edit_plan_request(brief, segments, self._model)
        response = await self._provider.generate(request)
        try:
            return _validated_plan(response, brief, segments)
        except InvalidModelResponseError:
            repair_request = _build_repair_request(request, response.content)

        repair_response = await self._provider.generate(repair_request)
        try:
            return _validated_plan(repair_response, brief, segments)
        except InvalidModelResponseError as error:
            raise InvalidModelResponseError(
                "Text model returned an invalid edit plan after one repair attempt."
            ) from error


__all__ = ["InvalidModelResponseError", "LlmPlanner", "parse_edit_plan_response"]
