"""Local segment-analysis details independent of classification decisions."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from minicut.edit_plan import (
    ContentRequirement,
    EditAction,
    EditBrief,
    EditDecision,
    ReasonCode,
)
from minicut.llm_provider import TextModelRequest
from minicut.semantic_segment import (
    SemanticSegment,
    validate_segment_context_dependencies,
)

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


@dataclass(slots=True)
class LocalAnalysisJudgment:
    """Classification and detail produced for the same local target."""

    classification: SegmentClassificationResult
    detail: SegmentAnalysisDetail

    def __post_init__(self) -> None:
        if self.classification.segment_id != self.detail.segment_id:
            raise ValueError(
                "local judgment components must reference the same Segment"
            )

    @property
    def segment_id(self) -> str:
        """Return the shared target Segment ID."""
        return self.classification.segment_id


@dataclass(slots=True)
class LocalSegmentAnalysis:
    """Deterministically merged local judgments for one source Segment."""

    segment_id: str
    classification: SegmentClassification
    importance: float
    dependency_ids: tuple[str, ...]
    rationale: str
    has_classification_conflict: bool

    def __post_init__(self) -> None:
        SegmentAnalysisDetail(
            self.segment_id,
            self.importance,
            self.dependency_ids,
            self.rationale,
        )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""
        return {
            "segment_id": self.segment_id,
            "classification": self.classification.value,
            "importance": self.importance,
            "dependency_ids": list(self.dependency_ids),
            "rationale": self.rationale,
            "has_classification_conflict": self.has_classification_conflict,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "LocalSegmentAnalysis":
        """Restore a merged local analysis from a JSON-compatible mapping."""
        detail = SegmentAnalysisDetail.from_dict(data)
        conflict = data["has_classification_conflict"]
        if not isinstance(conflict, bool):
            raise ValueError("classification conflict marker must be boolean")
        return cls(
            segment_id=detail.segment_id,
            classification=SegmentClassification(cast(str, data["classification"])),
            importance=detail.importance,
            dependency_ids=detail.dependency_ids,
            rationale=detail.rationale,
            has_classification_conflict=conflict,
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


def merge_local_judgments(
    segments: tuple[SemanticSegment, ...],
    judgments: tuple[LocalAnalysisJudgment, ...],
) -> tuple[LocalSegmentAnalysis, ...]:
    """Merge repeated window judgments conservatively in source order."""
    validate_segment_context_dependencies(segments)
    segment_ids = tuple(segment.segment_id for segment in segments)
    known_ids = set(segment_ids)
    unknown_ids = {judgment.segment_id for judgment in judgments} - known_ids
    if unknown_ids:
        raise ValueError("local judgments reference an unknown Segment ID")

    judgments_by_id: dict[str, list[LocalAnalysisJudgment]] = {
        segment_id: [] for segment_id in segment_ids
    }
    for judgment in judgments:
        judgments_by_id[judgment.segment_id].append(judgment)
    if any(not items for items in judgments_by_id.values()):
        raise ValueError("local judgments are missing a Segment analysis")

    unknown_dependencies = {
        dependency_id
        for judgment in judgments
        for dependency_id in judgment.detail.dependency_ids
        if dependency_id not in known_ids
    }
    if unknown_dependencies:
        raise ValueError("local judgment dependency references an unknown Segment ID")

    merged: list[LocalSegmentAnalysis] = []
    for segment_id in segment_ids:
        items = judgments_by_id[segment_id]
        classifications = {item.classification.classification for item in items}
        has_conflict = len(classifications) > 1
        classification = (
            SegmentClassification.CONTENT
            if has_conflict
            else items[0].classification.classification
        )
        most_important = max(items, key=lambda item: item.detail.importance)
        dependency_set = {
            dependency_id
            for item in items
            for dependency_id in item.detail.dependency_ids
        }
        dependencies = tuple(
            candidate_id
            for candidate_id in segment_ids
            if candidate_id in dependency_set
        )
        merged.append(
            LocalSegmentAnalysis(
                segment_id=segment_id,
                classification=classification,
                importance=most_important.detail.importance,
                dependency_ids=dependencies,
                rationale=most_important.detail.rationale,
                has_classification_conflict=has_conflict,
            )
        )
    return tuple(merged)


def _requirement_ids(
    requirements: tuple[ContentRequirement, ...],
) -> set[str]:
    return {
        segment_id
        for requirement in requirements
        for segment_id in requirement.segment_ids
    }


def build_local_decisions(
    brief: EditBrief,
    segments: tuple[SemanticSegment, ...],
    analyses: tuple[LocalSegmentAnalysis, ...],
) -> tuple[EditDecision, ...]:
    """Convert merged analyses to protected decisions with standard reasons."""
    validate_segment_context_dependencies(segments)
    segment_ids = tuple(segment.segment_id for segment in segments)
    analysis_ids = tuple(analysis.segment_id for analysis in analyses)
    if len(set(analysis_ids)) != len(analysis_ids):
        raise ValueError("local analyses contain duplicate Segment IDs")
    if set(analysis_ids) - set(segment_ids):
        raise ValueError("local analyses reference an unknown Segment ID")
    if set(segment_ids) - set(analysis_ids):
        raise ValueError("local analyses are missing a Segment")

    analyses_by_id = {analysis.segment_id: analysis for analysis in analyses}
    segments_by_id = {segment.segment_id: segment for segment in segments}
    must_keep_ids = _requirement_ids(brief.must_keep)
    must_remove_ids = _requirement_ids(brief.must_remove)
    unknown_requirement_ids = (must_keep_ids | must_remove_ids) - set(segment_ids)
    if unknown_requirement_ids:
        raise ValueError("content requirement references an unknown Segment ID")
    if must_keep_ids & must_remove_ids:
        raise ValueError("must_keep and must_remove Segment requirements conflict")

    deleted_ids = {
        analysis.segment_id
        for analysis in analyses
        if analysis.classification is not SegmentClassification.CONTENT
        and not analysis.has_classification_conflict
    } | must_remove_ids
    deleted_ids -= must_keep_ids
    context_required_ids: set[str] = set()

    changed = True
    while changed:
        changed = False
        for segment_id in segment_ids:
            if segment_id in deleted_ids:
                continue
            analysis = analyses_by_id[segment_id]
            semantic_dependencies = tuple(
                dependency.segment_id
                for dependency in segments_by_id[segment_id].context_dependencies
            )
            for dependency_id in analysis.dependency_ids + semantic_dependencies:
                if dependency_id not in deleted_ids:
                    continue
                if dependency_id in must_remove_ids:
                    raise ValueError(
                        "must_remove requirement conflicts with kept context"
                    )
                deleted_ids.remove(dependency_id)
                context_required_ids.add(dependency_id)
                changed = True

    reason_by_classification = {
        SegmentClassification.FILLER: ReasonCode.FILLER,
        SegmentClassification.REPEAT: ReasonCode.REPETITION,
        SegmentClassification.FALSE_START: ReasonCode.FALSE_START,
    }
    decisions: list[EditDecision] = []
    for segment_id in segment_ids:
        analysis = analyses_by_id[segment_id]
        labels = [analysis.classification.value]
        if analysis.has_classification_conflict:
            labels.append("classification_conflict")
        if segment_id in context_required_ids:
            labels.append("context_required")

        if segment_id in must_keep_ids:
            action = EditAction.KEEP
            reason = ReasonCode.USER_REQUIRED
            explanation = "Kept because the user explicitly required this segment."
            confidence = 1.0
        elif segment_id in must_remove_ids:
            action = EditAction.DELETE
            reason = ReasonCode.USER_REQUIRED
            explanation = "Deleted because the user explicitly required its removal."
            confidence = 1.0
        elif segment_id in deleted_ids:
            action = EditAction.DELETE
            reason = reason_by_classification[analysis.classification]
            explanation = analysis.rationale
            confidence = 0.5
        else:
            action = EditAction.KEEP
            reason = ReasonCode.CONTENT
            explanation = analysis.rationale
            confidence = 0.5

        decisions.append(
            EditDecision(
                segment_id=segment_id,
                action=action,
                reason=reason,
                confidence=confidence,
                explanation=explanation,
                labels=tuple(labels),
            )
        )
    return tuple(decisions)


__all__ = [
    "LocalAnalysisJudgment",
    "LocalSegmentAnalysis",
    "SEGMENT_CLASSIFICATION_PROMPT_VERSION",
    "SEGMENT_DETAIL_PROMPT_VERSION",
    "SegmentAnalysisDetail",
    "SegmentClassification",
    "SegmentClassificationResult",
    "build_local_decisions",
    "build_segment_classification_request",
    "build_segment_detail_request",
    "merge_local_judgments",
    "parse_segment_classification_response",
    "parse_segment_detail_response",
]
