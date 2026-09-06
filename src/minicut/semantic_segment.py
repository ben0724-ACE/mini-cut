"""Editable semantic segment domain models."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import cast


class ContextDirection(StrEnum):
    """Where a required context segment appears relative to its owner."""

    PRECEDING = "preceding"
    FOLLOWING = "following"


@dataclass(slots=True)
class SegmentContextDependency:
    """A directional reference to context required by a segment."""

    segment_id: str
    direction: ContextDirection

    def __post_init__(self) -> None:
        if not self.segment_id.strip():
            raise ValueError("dependency segment ID must not be blank")

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""
        return {
            "segment_id": self.segment_id,
            "direction": self.direction.value,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "SegmentContextDependency":
        """Restore a dependency from a JSON-compatible mapping."""
        return cls(
            segment_id=cast(str, data["segment_id"]),
            direction=ContextDirection(cast(str, data["direction"])),
        )


@dataclass(slots=True)
class SemanticSegment:
    """A traceable unit that can independently receive an edit decision."""

    segment_id: str
    text: str
    start_ms: int
    end_ms: int
    utterance_ids: tuple[str, ...]
    word_ids: tuple[str, ...]
    context_dependencies: tuple[SegmentContextDependency, ...] = ()

    def __post_init__(self) -> None:
        if not self.segment_id.strip():
            raise ValueError("segment ID must not be blank")
        if not self.text.strip():
            raise ValueError("segment text must not be blank")
        if self.start_ms < 0 or self.end_ms <= self.start_ms:
            raise ValueError(
                "SemanticSegment time range must have a non-negative start and later end"
            )
        self._validate_coverage("utterance", self.utterance_ids)
        self._validate_coverage("word", self.word_ids)

        dependency_ids = tuple(
            dependency.segment_id for dependency in self.context_dependencies
        )
        if self.segment_id in dependency_ids:
            raise ValueError("segment cannot have a context dependency on itself")
        if len(set(dependency_ids)) != len(dependency_ids):
            raise ValueError("segment context dependency IDs must be unique")

    @staticmethod
    def _validate_coverage(label: str, identifiers: tuple[str, ...]) -> None:
        if not identifiers or any(not identifier.strip() for identifier in identifiers):
            raise ValueError(f"segment {label} coverage must not be empty")
        if len(set(identifiers)) != len(identifiers):
            raise ValueError(f"segment {label} coverage IDs must be unique")

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""
        return {
            "segment_id": self.segment_id,
            "text": self.text,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "utterance_ids": list(self.utterance_ids),
            "word_ids": list(self.word_ids),
            "context_dependencies": [
                dependency.to_dict() for dependency in self.context_dependencies
            ],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "SemanticSegment":
        """Restore a segment from a JSON-compatible mapping."""
        dependency_data = cast(
            list[dict[str, object]],
            data["context_dependencies"],
        )
        return cls(
            segment_id=cast(str, data["segment_id"]),
            text=cast(str, data["text"]),
            start_ms=cast(int, data["start_ms"]),
            end_ms=cast(int, data["end_ms"]),
            utterance_ids=tuple(cast(list[str], data["utterance_ids"])),
            word_ids=tuple(cast(list[str], data["word_ids"])),
            context_dependencies=tuple(
                SegmentContextDependency.from_dict(dependency)
                for dependency in dependency_data
            ),
        )


def generate_segment_id(transcript_id: str, ordinal: int) -> str:
    """Generate a stable, readable ID without adding another content hash."""
    if not transcript_id.strip():
        raise ValueError("transcript ID must not be blank")
    if ordinal < 0:
        raise ValueError("ordinal must not be negative")
    return f"segment:{transcript_id}:{ordinal}"


def validate_segment_context_dependencies(
    segments: tuple[SemanticSegment, ...],
) -> None:
    """Validate dependency references and their declared temporal direction."""
    segments_by_id = {segment.segment_id: segment for segment in segments}
    if len(segments_by_id) != len(segments):
        raise ValueError("segment IDs must be unique")

    for segment in segments:
        for dependency in segment.context_dependencies:
            target = segments_by_id.get(dependency.segment_id)
            if target is None:
                raise ValueError("segment context dependency references an unknown ID")
            if (
                dependency.direction is ContextDirection.PRECEDING
                and target.end_ms > segment.start_ms
            ) or (
                dependency.direction is ContextDirection.FOLLOWING
                and target.start_ms < segment.end_ms
            ):
                raise ValueError("segment context dependency direction is inconsistent")


__all__ = [
    "ContextDirection",
    "SegmentContextDependency",
    "SemanticSegment",
    "generate_segment_id",
    "validate_segment_context_dependencies",
]
