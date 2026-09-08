"""LLM-backed structured edit planning with one controlled repair."""

import asyncio
import json
from typing import cast

from minicut.edit_plan import (
    EditBrief,
    EditDecision,
    EditPlan,
    PlannerKind,
    PlanProvenance,
    validate_edit_plan,
)
from minicut.errors import ProcessingError
from minicut.llm_prompt import EDIT_PLAN_PROMPT_VERSION, build_edit_plan_request
from minicut.llm_provider import (
    TextModelProvider,
    TextModelProviderError,
    TextModelRateLimitError,
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
LLM_POLICY_VERSION = "llm-policy-v1"


class InvalidModelResponseError(ProcessingError):
    """Raised when model output cannot become a validated EditPlan."""


class ModelProviderError(ProcessingError):
    """Raised when a text-model provider cannot complete a request."""


class ModelRateLimitError(ModelProviderError):
    """Raised when the configured text-model provider is rate limited."""


class ModelTimeoutError(ModelProviderError):
    """Raised when a text-model request exceeds its configured time limit."""


def parse_edit_plan_response(
    content: str,
    brief: EditBrief,
    provenance: PlanProvenance,
) -> EditPlan:
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
        return EditPlan(brief, tuple(decisions), summary, provenance)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise InvalidModelResponseError(
            "Text model returned an invalid edit plan."
        ) from error


def _validated_plan(
    response: TextModelResponse,
    brief: EditBrief,
    segments: tuple[SemanticSegment, ...],
) -> EditPlan:
    provenance = PlanProvenance(
        planner=PlannerKind.LLM,
        model=response.model,
        prompt_version=EDIT_PLAN_PROMPT_VERSION,
        policy_version=LLM_POLICY_VERSION,
    )
    plan = parse_edit_plan_response(response.content, brief, provenance)
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

    def __init__(
        self,
        provider: TextModelProvider,
        model: str,
        *,
        timeout_seconds: float = 60.0,
    ) -> None:
        if not model.strip():
            raise ValueError("planner model must not be blank")
        if timeout_seconds <= 0:
            raise ValueError("planner timeout must be positive")
        self._provider = provider
        self._model = model
        self._timeout_seconds = timeout_seconds

    @property
    def model(self) -> str:
        """Return the configured request model name."""
        return self._model

    async def _generate(self, request: TextModelRequest) -> TextModelResponse:
        try:
            return await asyncio.wait_for(
                self._provider.generate(request),
                timeout=self._timeout_seconds,
            )
        except asyncio.CancelledError:
            raise
        except TimeoutError as error:
            raise ModelTimeoutError("Text model request timed out.") from error
        except TextModelRateLimitError as error:
            raise ModelRateLimitError(
                "Text model provider rate limit was reached."
            ) from error
        except TextModelProviderError as error:
            raise ModelProviderError("Text model provider request failed.") from error
        except Exception as error:
            raise ModelProviderError("Text model provider request failed.") from error

    async def plan(
        self,
        brief: EditBrief,
        segments: tuple[SemanticSegment, ...],
    ) -> EditPlan:
        """Generate a plan, allowing exactly one repair of invalid output."""
        request = build_edit_plan_request(brief, segments, self._model)
        response = await self._generate(request)
        try:
            return _validated_plan(response, brief, segments)
        except InvalidModelResponseError:
            repair_request = _build_repair_request(request, response.content)

        repair_response = await self._generate(repair_request)
        try:
            return _validated_plan(repair_response, brief, segments)
        except InvalidModelResponseError as error:
            raise InvalidModelResponseError(
                "Text model returned an invalid edit plan after one repair attempt."
            ) from error


__all__ = [
    "InvalidModelResponseError",
    "LLM_POLICY_VERSION",
    "LlmPlanner",
    "ModelProviderError",
    "ModelRateLimitError",
    "ModelTimeoutError",
    "parse_edit_plan_response",
]
