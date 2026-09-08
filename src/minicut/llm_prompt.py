"""Deterministic prompts for structured LLM edit planning."""

import json

from minicut.edit_plan import EditAction, EditBrief, ReasonCode
from minicut.llm_provider import TextModelRequest
from minicut.semantic_segment import (
    SemanticSegment,
    validate_segment_context_dependencies,
)

EDIT_PLAN_PROMPT_VERSION = "edit-plan-v1"


def build_edit_plan_request(
    brief: EditBrief,
    segments: tuple[SemanticSegment, ...],
    model: str,
) -> TextModelRequest:
    """Build a stable request that exposes no source media timestamps."""
    validate_segment_context_dependencies(segments)
    actions = ", ".join(action.value for action in EditAction)
    reasons = ", ".join(reason.value for reason in ReasonCode)
    system_prompt = (
        "Return one JSON object with keys summary and decisions. "
        "Return exactly one decision for every ID in allowed_segment_ids and never "
        "reference any other ID. Each decision must contain only segment_id, action, "
        "reason, confidence, explanation, and labels. "
        f"Allowed actions: {actions}. Allowed reasons: {reasons}. "
        "confidence must be between 0 and 1. Do not return timestamps."
    )
    payload = {
        "prompt_version": EDIT_PLAN_PROMPT_VERSION,
        "brief": brief.to_dict(),
        "allowed_segment_ids": [segment.segment_id for segment in segments],
        "segments": [
            {
                "segment_id": segment.segment_id,
                "text": segment.text,
                "labels": [label.value for label in segment.labels],
                "context_segment_ids": [
                    dependency.segment_id for dependency in segment.context_dependencies
                ],
            }
            for segment in segments
        ],
    }
    return TextModelRequest(
        model=model,
        system_prompt=system_prompt,
        user_prompt=json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    )


__all__ = ["EDIT_PLAN_PROMPT_VERSION", "build_edit_plan_request"]
