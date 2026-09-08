"""Versioned timeline and clip domain models."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from minicut.edit_plan import EditAction, EditPlan, validate_edit_plan
from minicut.media import TimeRange
from minicut.semantic_segment import SemanticSegment

TIMELINE_SCHEMA_VERSION = 1


@dataclass(slots=True)
class Clip:
    """One source Segment mapped onto an output time range."""

    clip_id: str
    source_asset_id: str
    segment_id: str
    source_range: TimeRange
    output_range: TimeRange

    def __post_init__(self) -> None:
        if not self.clip_id.strip():
            raise ValueError("clip ID must not be blank")
        if not self.source_asset_id.strip():
            raise ValueError("clip source asset ID must not be blank")
        if not self.segment_id.strip():
            raise ValueError("clip Segment ID must not be blank")

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""
        return {
            "clip_id": self.clip_id,
            "source_asset_id": self.source_asset_id,
            "segment_id": self.segment_id,
            "source_range": {
                "start_ms": self.source_range.start_ms,
                "end_ms": self.source_range.end_ms,
            },
            "output_range": {
                "start_ms": self.output_range.start_ms,
                "end_ms": self.output_range.end_ms,
            },
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "Clip":
        """Restore a clip from a JSON-compatible mapping."""
        source_range = cast(Mapping[str, object], data["source_range"])
        output_range = cast(Mapping[str, object], data["output_range"])
        return cls(
            clip_id=cast(str, data["clip_id"]),
            source_asset_id=cast(str, data["source_asset_id"]),
            segment_id=cast(str, data["segment_id"]),
            source_range=TimeRange(
                cast(int, source_range["start_ms"]),
                cast(int, source_range["end_ms"]),
            ),
            output_range=TimeRange(
                cast(int, output_range["start_ms"]),
                cast(int, output_range["end_ms"]),
            ),
        )


@dataclass(slots=True)
class Timeline:
    """A versioned ordered collection of output clips."""

    clips: tuple[Clip, ...]
    estimated_duration_ms: int
    schema_version: int = TIMELINE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if (
            type(self.schema_version) is not int
            or self.schema_version != TIMELINE_SCHEMA_VERSION
        ):
            raise ValueError(
                f"Unsupported Timeline schema version: {self.schema_version}"
            )
        if self.estimated_duration_ms < 0:
            raise ValueError("timeline estimated duration must not be negative")

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""
        return {
            "schema_version": self.schema_version,
            "clips": [clip.to_dict() for clip in self.clips],
            "estimated_duration_ms": self.estimated_duration_ms,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "Timeline":
        """Restore a timeline from a JSON-compatible mapping."""
        clips = cast(list[Mapping[str, object]], data["clips"])
        return cls(
            clips=tuple(Clip.from_dict(clip) for clip in clips),
            estimated_duration_ms=cast(int, data["estimated_duration_ms"]),
            schema_version=cast(int, data["schema_version"]),
        )


def resolve_kept_segments(
    plan: EditPlan,
    segments: tuple[SemanticSegment, ...],
) -> tuple[SemanticSegment, ...]:
    """Resolve validated keep decisions and sort them by source time."""
    validate_edit_plan(plan, segments)
    kept_ids = {
        decision.segment_id
        for decision in plan.decisions
        if decision.action is EditAction.KEEP
    }
    kept_segments = tuple(
        sorted(
            (segment for segment in segments if segment.segment_id in kept_ids),
            key=lambda segment: (
                segment.start_ms,
                segment.end_ms,
                segment.segment_id,
            ),
        )
    )
    if not kept_segments:
        raise ValueError("edit plan contains no kept Segments")
    return kept_segments


def compile_timeline(
    plan: EditPlan,
    segments: tuple[SemanticSegment, ...],
    source_asset_id: str,
) -> Timeline:
    """Compile keep decisions into contiguous output ranges without media I/O."""
    if not source_asset_id.strip():
        raise ValueError("timeline source asset ID must not be blank")
    kept_segments = resolve_kept_segments(plan, segments)
    clips: list[Clip] = []
    output_cursor_ms = 0
    for ordinal, segment in enumerate(kept_segments):
        source_range = TimeRange(segment.start_ms, segment.end_ms)
        output_end_ms = output_cursor_ms + source_range.duration_ms
        clips.append(
            Clip(
                clip_id=f"clip:{ordinal}",
                source_asset_id=source_asset_id,
                segment_id=segment.segment_id,
                source_range=source_range,
                output_range=TimeRange(output_cursor_ms, output_end_ms),
            )
        )
        output_cursor_ms = output_end_ms
    return Timeline(tuple(clips), output_cursor_ms)


__all__ = [
    "TIMELINE_SCHEMA_VERSION",
    "Clip",
    "Timeline",
    "compile_timeline",
    "resolve_kept_segments",
]
