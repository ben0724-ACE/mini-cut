"""Local segment-analysis details independent of classification decisions."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from minicut.llm_provider import TextModelRequest
from minicut.semantic_segment import SemanticSegment

SEGMENT_CLASSIFICATION_PROMPT_VERSION = "segment-classification-v1"
SEGMENT_DETAIL_PROMPT_VERSION = "segment-detail-v1"
_CLASSIFICATION_FIELDS = {"segment_id", "classification"}
_DETAIL_FIELDS = {"segment_id", "importance", "dependency_ids", "rationale"}


class SegmentClassification(StrEnum):
    """Supported local semantic classifications for one target Segment."""

    FILLER = "filler"
    REPEAT = "repeat"
    FALSE_START = "false_start"
    CONTENT = "content"


@dataclass(slots=True)
class SegmentClassificationResult:
    """One classification that can only reference its target Segment."""

    segment_id: str
    classification: SegmentClassification

    def __post_init__(self) -> None:
        if not self.segment_id.strip():
            raise ValueError("classification Segment ID must not be blank")

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""
        return {
            "segment_id": self.segment_id,
            "classification": self.classification.value,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "SegmentClassificationResult":
        """Restore a target classification from a JSON-compatible mapping."""
        return cls(
            segment_id=cast(str, data["segment_id"]),
            classification=SegmentClassification(cast(str, data["classification"])),
        )


@dataclass(slots=True)
class SegmentAnalysisDetail:
    """Importance, contextual dependencies, and a short model rationale."""

    segment_id: str
    importance: float
    dependency_ids: tuple[str, ...]
    rationale: str

    def __post_init__(self) -> None:
        if not self.segment_id.strip():
            raise ValueError("analysis detail Segment ID must not be blank")
        if isinstance(self.importance, bool) or not 0.0 <= self.importance <= 1.0:
            raise ValueError("analysis detail importance must be between zero and one")
        if any(not dependency_id.strip() for dependency_id in self.dependency_ids):
            raise ValueError("analysis detail dependency IDs must not be blank")
        if self.segment_id in self.dependency_ids:
            raise ValueError("analysis detail cannot depend on its own Segment ID")
        if len(set(self.dependency_ids)) != len(self.dependency_ids):
            raise ValueError("analysis detail dependency IDs must be unique")
        rationale = self.rationale.strip()
        if not rationale:
            raise ValueError("analysis detail rationale must not be blank")
        if len(rationale) > 200:
            raise ValueError("analysis detail rationale must not exceed 200 characters")

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""
        return {
            "segment_id": self.segment_id,
            "importance": self.importance,
            "dependency_ids": list(self.dependency_ids),
            "rationale": self.rationale,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "SegmentAnalysisDetail":
        """Restore analysis details from a JSON-compatible mapping."""
        raw_importance = data["importance"]
        if isinstance(raw_importance, bool) or not isinstance(
            raw_importance, (int, float)
        ):
            raise ValueError("analysis detail importance must be numeric")
        return cls(
            segment_id=cast(str, data["segment_id"]),
            importance=float(raw_importance),
            dependency_ids=tuple(cast(list[str], data["dependency_ids"])),
            rationale=cast(str, data["rationale"]),
        )


def _prompt_segment(segment: SemanticSegment) -> dict[str, object]:
    return {
        "segment_id": segment.segment_id,
        "text": segment.text,
        "labels": [label.value for label in segment.labels],
    }


def _validate_context(
    target: SemanticSegment,
    context: tuple[SemanticSegment, ...],
) -> None:
    context_ids = tuple(segment.segment_id for segment in context)
    if target.segment_id in context_ids:
        raise ValueError("analysis context must not contain the target Segment")
    if len(set(context_ids)) != len(context_ids):
        raise ValueError("analysis context Segment IDs must be unique")


def build_segment_classification_request(
    target: SemanticSegment,
    context: tuple[SemanticSegment, ...],
    model: str,
) -> TextModelRequest:
    """Build a request that classifies only one target Segment."""
    _validate_context(target, context)
    classifications = ", ".join(
        classification.value for classification in SegmentClassification
    )
    system_prompt = (
        "Return one JSON object with exactly segment_id and classification. "
        "Classify only the target Segment as exactly one of: "
        f"{classifications}. The read_only_context is provided only to interpret "
        "the target; you must not classify, modify, or make edit decisions for any "
        "context Segment. Return the target segment_id unchanged."
    )
    payload = {
        "prompt_version": SEGMENT_CLASSIFICATION_PROMPT_VERSION,
        "target": _prompt_segment(target),
        "read_only_context": [_prompt_segment(segment) for segment in context],
    }
    return TextModelRequest(
        model=model,
        system_prompt=system_prompt,
        user_prompt=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
    )


def parse_segment_classification_response(
    content: str,
    target: SemanticSegment,
    context: tuple[SemanticSegment, ...],
) -> SegmentClassificationResult:
    """Strictly parse a classification for the requested target only."""
    _validate_context(target, context)
    try:
        loaded: object = json.loads(content)
        if not isinstance(loaded, dict):
            raise TypeError("classification root must be an object")
        data = cast(dict[str, object], loaded)
        if set(data) != _CLASSIFICATION_FIELDS:
            raise ValueError("classification fields are invalid")
        result = SegmentClassificationResult.from_dict(data)
        if result.segment_id != target.segment_id:
            raise ValueError("classification must reference the target Segment")
        return result
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise ValueError("invalid segment classification") from error


def build_segment_detail_request(
    target: SemanticSegment,
    context: tuple[SemanticSegment, ...],
    model: str,
) -> TextModelRequest:
    """Build a request whose neighboring context is read-only."""
    _validate_context(target, context)
    system_prompt = (
        "Return one JSON object with exactly segment_id, importance, "
        "dependency_ids, and rationale. Analyze only the target Segment. "
        "The read_only_context may be referenced by dependency_ids but you must not "
        "modify, classify, or make edit decisions for context Segments. "
        "importance must be between 0 and 1. dependency_ids may only contain IDs "
        "from read_only_context. rationale must be concise and at most 200 characters."
    )
    payload = {
        "prompt_version": SEGMENT_DETAIL_PROMPT_VERSION,
        "target": _prompt_segment(target),
        "read_only_context": [_prompt_segment(segment) for segment in context],
    }
    return TextModelRequest(
        model=model,
        system_prompt=system_prompt,
        user_prompt=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
    )


def parse_segment_detail_response(
    content: str,
    target: SemanticSegment,
    context: tuple[SemanticSegment, ...],
) -> SegmentAnalysisDetail:
    """Parse details and constrain references to the supplied read-only context."""
    _validate_context(target, context)
    try:
        loaded: object = json.loads(content)
        if not isinstance(loaded, dict):
            raise TypeError("analysis detail root must be an object")
        data = cast(dict[str, object], loaded)
        if set(data) != _DETAIL_FIELDS:
            raise ValueError("analysis detail fields are invalid")
        detail = SegmentAnalysisDetail.from_dict(data)
        if detail.segment_id != target.segment_id:
            raise ValueError("analysis detail must reference the target Segment")
        context_ids = {segment.segment_id for segment in context}
        if not set(detail.dependency_ids) <= context_ids:
            raise ValueError("analysis detail references unknown context")
        return detail
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise ValueError("invalid segment analysis detail") from error


__all__ = [
    "SEGMENT_CLASSIFICATION_PROMPT_VERSION",
    "SEGMENT_DETAIL_PROMPT_VERSION",
    "SegmentAnalysisDetail",
    "SegmentClassification",
    "SegmentClassificationResult",
    "build_segment_classification_request",
    "build_segment_detail_request",
    "parse_segment_classification_response",
    "parse_segment_detail_response",
]
