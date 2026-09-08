"""Global narrative outline built from merged local Segment analyses."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from minicut.edit_plan import EditBrief
from minicut.llm_provider import TextModelRequest
from minicut.local_analysis import LocalSegmentAnalysis
from minicut.semantic_segment import (
    SemanticSegment,
    validate_segment_context_dependencies,
)

NARRATIVE_OUTLINE_PROMPT_VERSION = "narrative-outline-v1"
_OUTLINE_FIELDS = {"topic", "opening", "core_points", "conclusion"}
_SECTION_FIELDS = {"summary", "segment_ids"}


@dataclass(slots=True)
class NarrativeSection:
    """One narrative role and the source Segments that support it."""

    summary: str
    segment_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.summary.strip():
            raise ValueError("narrative section summary must not be blank")
        if not self.segment_ids:
            raise ValueError("narrative section must reference at least one Segment")
        if any(not segment_id.strip() for segment_id in self.segment_ids):
            raise ValueError("narrative section Segment IDs must not be blank")
        if len(set(self.segment_ids)) != len(self.segment_ids):
            raise ValueError("narrative section Segment IDs must be unique")

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""
        return {"summary": self.summary, "segment_ids": list(self.segment_ids)}

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "NarrativeSection":
        """Restore a narrative section from a JSON-compatible mapping."""
        raw_ids = data["segment_ids"]
        if not isinstance(raw_ids, list):
            raise ValueError("narrative section Segment IDs must be a list")
        return cls(
            summary=cast(str, data["summary"]),
            segment_ids=tuple(cast(list[str], raw_ids)),
        )


@dataclass(slots=True)
class NarrativeOutline:
    """Topic, opening, core points, and conclusion for one source."""

    topic: str
    opening: NarrativeSection
    core_points: tuple[NarrativeSection, ...]
    conclusion: NarrativeSection

    def __post_init__(self) -> None:
        if not self.topic.strip():
            raise ValueError("narrative outline topic must not be blank")
        if not self.core_points:
            raise ValueError("narrative outline must contain at least one core point")

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""
        return {
            "topic": self.topic,
            "opening": self.opening.to_dict(),
            "core_points": [point.to_dict() for point in self.core_points],
            "conclusion": self.conclusion.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "NarrativeOutline":
        """Restore an outline from a JSON-compatible mapping."""
        opening = cast(Mapping[str, object], data["opening"])
        raw_core_points = cast(list[Mapping[str, object]], data["core_points"])
        conclusion = cast(Mapping[str, object], data["conclusion"])
        return cls(
            topic=cast(str, data["topic"]),
            opening=NarrativeSection.from_dict(opening),
            core_points=tuple(
                NarrativeSection.from_dict(point) for point in raw_core_points
            ),
            conclusion=NarrativeSection.from_dict(conclusion),
        )


def _analyses_by_segment(
    segments: tuple[SemanticSegment, ...],
    analyses: tuple[LocalSegmentAnalysis, ...],
) -> dict[str, LocalSegmentAnalysis]:
    validate_segment_context_dependencies(segments)
    segment_ids = tuple(segment.segment_id for segment in segments)
    analysis_ids = tuple(analysis.segment_id for analysis in analyses)
    if len(set(analysis_ids)) != len(analysis_ids):
        raise ValueError("local analyses contain duplicate Segment IDs")
    if set(analysis_ids) != set(segment_ids):
        raise ValueError("local analyses must exactly cover the source Segments")
    return {analysis.segment_id: analysis for analysis in analyses}


def build_narrative_outline_request(
    brief: EditBrief,
    segments: tuple[SemanticSegment, ...],
    analyses: tuple[LocalSegmentAnalysis, ...],
    model: str,
) -> TextModelRequest:
    """Build a constrained request for narrative roles, not edit decisions."""
    analyses_by_id = _analyses_by_segment(segments, analyses)
    system_prompt = (
        "Return one JSON object with exactly topic, opening, core_points, and "
        "conclusion. opening and conclusion must each be an object with exactly "
        "summary and segment_ids. core_points must be a non-empty array of objects "
        "with those same fields. Every narrative section must reference at least "
        "one ID from allowed_segment_ids, and no other ID. Describe the global "
        "story structure only: do not add timestamps, source text, keep/delete "
        "decisions, or new facts."
    )
    payload = {
        "prompt_version": NARRATIVE_OUTLINE_PROMPT_VERSION,
        "brief": brief.to_dict(),
        "allowed_segment_ids": [segment.segment_id for segment in segments],
        "segments": [
            {
                "segment_id": segment.segment_id,
                "text": segment.text,
                **analyses_by_id[segment.segment_id].to_dict(),
            }
            for segment in segments
        ],
    }
    return TextModelRequest(
        model=model,
        system_prompt=system_prompt,
        user_prompt=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
    )


def _parse_section(value: object) -> NarrativeSection:
    if not isinstance(value, dict):
        raise TypeError("narrative section must be an object")
    section_data = cast(dict[str, object], value)
    if set(section_data) != _SECTION_FIELDS:
        raise ValueError("narrative section fields are invalid")
    return NarrativeSection.from_dict(section_data)


def parse_narrative_outline_response(
    content: str,
    segments: tuple[SemanticSegment, ...],
) -> NarrativeOutline:
    """Strictly parse an outline whose evidence references known Segments."""
    validate_segment_context_dependencies(segments)
    allowed_ids = {segment.segment_id for segment in segments}
    try:
        loaded: object = json.loads(content)
        if not isinstance(loaded, dict):
            raise TypeError("narrative outline root must be an object")
        data = cast(dict[str, object], loaded)
        if set(data) != _OUTLINE_FIELDS:
            raise ValueError("narrative outline fields are invalid")
        raw_points = data["core_points"]
        if not isinstance(raw_points, list):
            raise TypeError("narrative core points must be an array")
        points = cast(list[object], raw_points)
        outline = NarrativeOutline(
            topic=cast(str, data["topic"]),
            opening=_parse_section(data["opening"]),
            core_points=tuple(_parse_section(point) for point in points),
            conclusion=_parse_section(data["conclusion"]),
        )
        referenced_ids = {
            segment_id
            for section in (outline.opening, *outline.core_points, outline.conclusion)
            for segment_id in section.segment_ids
        }
        if not referenced_ids <= allowed_ids:
            raise ValueError("narrative outline references an unknown Segment ID")
        return outline
    except (
        AttributeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ) as error:
        raise ValueError("invalid narrative outline") from error


__all__ = [
    "NARRATIVE_OUTLINE_PROMPT_VERSION",
    "NarrativeOutline",
    "NarrativeSection",
    "build_narrative_outline_request",
    "parse_narrative_outline_response",
]
