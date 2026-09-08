"""User editing brief and structured edit plan domain models."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from minicut.semantic_segment import (
    SemanticSegment,
    validate_segment_context_dependencies,
)

EDIT_PLAN_SCHEMA_VERSION = 1


class EditIntensity(StrEnum):
    """How aggressively removable content may be shortened."""

    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    AGGRESSIVE = "aggressive"


class EditAction(StrEnum):
    """The only edit actions allowed for one source segment."""

    KEEP = "keep"
    DELETE = "delete"


class ReasonCode(StrEnum):
    """Machine-readable explanations for edit decisions."""

    USER_REQUIRED = "user_required"
    CONTENT = "content"
    SILENCE = "silence"
    FILLER = "filler"
    FALSE_START = "false_start"
    REPETITION = "repetition"
    TARGET_DURATION = "target_duration"


class PlannerKind(StrEnum):
    """The planning implementation that produced an EditPlan."""

    RULE = "rule"
    LLM = "llm"


@dataclass(slots=True)
class PlanProvenance:
    """Reproducibility metadata without prompts or provider credentials."""

    planner: PlannerKind
    model: str
    prompt_version: str
    policy_version: str

    def __post_init__(self) -> None:
        if not self.model.strip():
            raise ValueError("plan provenance model must not be blank")
        if not self.prompt_version.strip():
            raise ValueError("plan provenance prompt version must not be blank")
        if not self.policy_version.strip():
            raise ValueError("plan provenance policy version must not be blank")

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""
        return {
            "planner": self.planner.value,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "policy_version": self.policy_version,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "PlanProvenance":
        """Restore plan provenance from a JSON-compatible mapping."""
        return cls(
            planner=PlannerKind(cast(str, data["planner"])),
            model=cast(str, data["model"]),
            prompt_version=cast(str, data["prompt_version"]),
            policy_version=cast(str, data["policy_version"]),
        )


@dataclass(slots=True)
class ContentRequirement:
    """Natural-language content intent with optional resolved Segment IDs."""

    instruction: str
    segment_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.instruction.strip():
            raise ValueError("content requirement instruction must not be blank")
        if any(not segment_id.strip() for segment_id in self.segment_ids):
            raise ValueError("content requirement Segment IDs must not be blank")
        if len(set(self.segment_ids)) != len(self.segment_ids):
            raise ValueError("content requirement Segment IDs must be unique")

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""
        return {
            "instruction": self.instruction,
            "segment_ids": list(self.segment_ids),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "ContentRequirement":
        """Restore a content requirement from a JSON-compatible mapping."""
        return cls(
            instruction=cast(str, data["instruction"]),
            segment_ids=tuple(cast(list[str], data["segment_ids"])),
        )


@dataclass(slots=True)
class EditBrief:
    """User-owned goals and constraints for one edit plan."""

    target_duration_ms: int
    intensity: EditIntensity
    style: str
    content_type: str = "spoken_video"
    language: str = "auto"
    must_keep: tuple[ContentRequirement, ...] = ()
    must_remove: tuple[ContentRequirement, ...] = ()

    def __post_init__(self) -> None:
        if self.target_duration_ms <= 0:
            raise ValueError("target duration must be positive")
        if not self.style.strip():
            raise ValueError("edit style must not be blank")
        if not self.content_type.strip():
            raise ValueError("content type must not be blank")
        if not self.language.strip():
            raise ValueError("language must not be blank")

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""
        return {
            "target_duration_ms": self.target_duration_ms,
            "intensity": self.intensity.value,
            "style": self.style,
            "content_type": self.content_type,
            "language": self.language,
            "must_keep": [requirement.to_dict() for requirement in self.must_keep],
            "must_remove": [requirement.to_dict() for requirement in self.must_remove],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "EditBrief":
        """Restore an edit brief from a JSON-compatible mapping."""
        keep_data = cast(list[dict[str, object]], data["must_keep"])
        remove_data = cast(list[dict[str, object]], data["must_remove"])
        return cls(
            target_duration_ms=cast(int, data["target_duration_ms"]),
            intensity=EditIntensity(cast(str, data["intensity"])),
            style=cast(str, data["style"]),
            content_type=cast(str, data["content_type"]),
            language=cast(str, data["language"]),
            must_keep=tuple(
                ContentRequirement.from_dict(requirement) for requirement in keep_data
            ),
            must_remove=tuple(
                ContentRequirement.from_dict(requirement) for requirement in remove_data
            ),
        )


@dataclass(slots=True)
class EditDecision:
    """One explainable keep or delete decision referencing a Segment ID."""

    segment_id: str
    action: EditAction
    reason: ReasonCode
    confidence: float
    explanation: str
    labels: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.segment_id.strip():
            raise ValueError("decision Segment ID must not be blank")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("decision confidence must be between zero and one")
        if not self.explanation.strip():
            raise ValueError("decision explanation must not be blank")
        if any(not label.strip() for label in self.labels):
            raise ValueError("decision labels must not be blank")
        if len(set(self.labels)) != len(self.labels):
            raise ValueError("decision labels must be unique")

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation without source timestamps."""
        return {
            "segment_id": self.segment_id,
            "action": self.action.value,
            "reason": self.reason.value,
            "confidence": self.confidence,
            "explanation": self.explanation,
            "labels": list(self.labels),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "EditDecision":
        """Restore an edit decision from a JSON-compatible mapping."""
        return cls(
            segment_id=cast(str, data["segment_id"]),
            action=EditAction(cast(str, data["action"])),
            reason=ReasonCode(cast(str, data["reason"])),
            confidence=cast(float, data["confidence"]),
            explanation=cast(str, data["explanation"]),
            labels=tuple(cast(list[str], data["labels"])),
        )


@dataclass(slots=True)
class EditPlan:
    """A versioned collection of structured decisions for an EditBrief."""

    brief: EditBrief
    decisions: tuple[EditDecision, ...]
    summary: str
    provenance: PlanProvenance
    schema_version: int = EDIT_PLAN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if (
            type(self.schema_version) is not int
            or self.schema_version != EDIT_PLAN_SCHEMA_VERSION
        ):
            raise ValueError(
                f"Unsupported EditPlan schema version: {self.schema_version}"
            )
        if not self.summary.strip():
            raise ValueError("edit plan summary must not be blank")

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""
        return {
            "schema_version": self.schema_version,
            "brief": self.brief.to_dict(),
            "decisions": [decision.to_dict() for decision in self.decisions],
            "summary": self.summary,
            "provenance": self.provenance.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "EditPlan":
        """Restore an edit plan from a JSON-compatible mapping."""
        brief_data = cast(dict[str, object], data["brief"])
        decision_data = cast(list[dict[str, object]], data["decisions"])
        provenance_data = cast(dict[str, object], data["provenance"])
        return cls(
            brief=EditBrief.from_dict(brief_data),
            decisions=tuple(
                EditDecision.from_dict(decision) for decision in decision_data
            ),
            summary=cast(str, data["summary"]),
            provenance=PlanProvenance.from_dict(provenance_data),
            schema_version=cast(int, data["schema_version"]),
        )


def _requirement_segment_ids(
    requirements: tuple[ContentRequirement, ...],
) -> tuple[str, ...]:
    return tuple(
        segment_id
        for requirement in requirements
        for segment_id in requirement.segment_ids
    )


def validate_edit_plan(
    plan: EditPlan,
    segments: tuple[SemanticSegment, ...],
) -> None:
    """Validate plan references and constraints against source segments."""
    validate_segment_context_dependencies(segments)
    segment_ids = {segment.segment_id for segment in segments}
    decision_ids = tuple(decision.segment_id for decision in plan.decisions)
    if len(set(decision_ids)) != len(decision_ids):
        raise ValueError("edit plan contains duplicate Segment decisions")

    unknown_decision_ids = set(decision_ids) - segment_ids
    if unknown_decision_ids:
        raise ValueError("edit plan references an unknown Segment ID")
    missing_decision_ids = segment_ids - set(decision_ids)
    if missing_decision_ids:
        raise ValueError("edit plan is missing a Segment decision")

    must_keep_ids = set(_requirement_segment_ids(plan.brief.must_keep))
    must_remove_ids = set(_requirement_segment_ids(plan.brief.must_remove))
    unknown_requirement_ids = (must_keep_ids | must_remove_ids) - segment_ids
    if unknown_requirement_ids:
        raise ValueError("content requirement references an unknown Segment ID")
    if must_keep_ids & must_remove_ids:
        raise ValueError("must_keep and must_remove Segment requirements conflict")

    decisions_by_id = {
        decision.segment_id: decision.action for decision in plan.decisions
    }
    if any(
        decisions_by_id[segment_id] is not EditAction.KEEP
        for segment_id in must_keep_ids
    ):
        raise ValueError("edit plan violates a must_keep requirement")
    if any(
        decisions_by_id[segment_id] is not EditAction.DELETE
        for segment_id in must_remove_ids
    ):
        raise ValueError("edit plan violates a must_remove requirement")

    for segment in segments:
        if decisions_by_id[segment.segment_id] is not EditAction.KEEP:
            continue
        if any(
            decisions_by_id[dependency.segment_id] is not EditAction.KEEP
            for dependency in segment.context_dependencies
        ):
            raise ValueError("kept Segment has a deleted context dependency")


__all__ = [
    "EDIT_PLAN_SCHEMA_VERSION",
    "ContentRequirement",
    "EditAction",
    "EditBrief",
    "EditDecision",
    "EditIntensity",
    "EditPlan",
    "PlanProvenance",
    "PlannerKind",
    "ReasonCode",
    "validate_edit_plan",
]
