"""Explicit-order compilation with validation bound to the source-ID plan."""

from dataclasses import dataclass

from minicut.media import MediaAsset, TimeRange
from minicut.output_plan import OutputPlan
from minicut.semantic_segment import (
    ContextDirection,
    SemanticSegment,
    validate_segment_context_dependencies,
)
from minicut.subtitle import MappedWord, map_retained_words
from minicut.timeline import Clip, Timeline
from minicut.timeline_validation import (
    TimelineDiagnosticSummary,
    TimelineTrackRequirements,
    TimelineValidationCode,
    TimelineValidationError,
    inspect_timeline_structure,
    inspect_timeline_tracks,
)
from minicut.transcript import Word


def compile_output_timeline(
    plan: OutputPlan,
    segments: tuple[SemanticSegment, ...],
    asset_id: str,
) -> Timeline:
    """Preserve item order and identity, resolving all timestamps locally."""
    if not asset_id.strip():
        raise ValueError("output source asset ID must not be blank")
    validate_segment_context_dependencies(segments)
    by_id = {segment.segment_id: segment for segment in segments}
    clips: list[Clip] = []
    cursor = 0
    for item in plan.items:
        segment = by_id.get(item.segment_id)
        if segment is None:
            raise ValueError("output references an unknown source segment")
        source = TimeRange(segment.start_ms, segment.end_ms)
        clips.append(
            Clip(
                item.instance_id,
                asset_id,
                segment.segment_id,
                source,
                TimeRange(cursor, cursor + source.duration_ms),
            )
        )
        cursor += source.duration_ms
    return Timeline(tuple(clips), cursor)


def validate_output_timeline(
    timeline: Timeline,
    plan: OutputPlan,
    segments: tuple[SemanticSegment, ...],
    asset_id: str,
    assets: tuple[MediaAsset, ...],
    requirements: TimelineTrackRequirements,
) -> TimelineDiagnosticSummary:
    """Only an exact explicit-plan compilation may reorder or reuse source."""
    expected = compile_output_timeline(plan, segments, asset_id)
    if timeline.to_dict() != expected.to_dict():
        raise ValueError("output timeline does not match its explicit source-ID plan")
    # Source chronology/overlap is intentional in this separate, plan-bound path.
    # The legacy validator and all other bounds/output/track checks stay intact.
    intentional = {
        TimelineValidationCode.SOURCE_ORDER,
        TimelineValidationCode.SOURCE_OVERLAP,
    }
    issues = tuple(
        issue
        for issue in inspect_timeline_structure(timeline, assets)
        if issue.code not in intentional
    )
    issues += inspect_timeline_tracks(timeline, assets, requirements)
    if issues:
        raise TimelineValidationError(issues)
    return TimelineDiagnosticSummary(
        len(timeline.clips), timeline.estimated_duration_ms
    )


@dataclass(frozen=True, slots=True)
class OutputContextIssue:
    instance_id: str
    segment_id: str
    context_segment_id: str
    message: str


def inspect_output_context(
    plan: OutputPlan,
    segments: tuple[SemanticSegment, ...],
) -> tuple[OutputContextIssue, ...]:
    """Report missing or misordered context per section, never invent speech."""
    validate_segment_context_dependencies(segments)
    by_id = {segment.segment_id: segment for segment in segments}
    issues: list[OutputContextIssue] = []
    for index, item in enumerate(plan.items):
        segment = by_id.get(item.segment_id)
        if segment is None:
            raise ValueError("output references an unknown source segment")
        for dependency in segment.context_dependencies:
            positions = [
                position
                for position, other in enumerate(plan.items)
                if other.role is item.role and other.segment_id == dependency.segment_id
            ]
            found = any(
                position < index
                if dependency.direction is ContextDirection.PRECEDING
                else position > index
                for position in positions
            )
            if not found:
                issues.append(
                    OutputContextIssue(
                        item.instance_id,
                        item.segment_id,
                        dependency.segment_id,
                        f"{item.role.value} lacks its required {dependency.direction.value} context; review the original wording.",
                    )
                )
    return tuple(issues)


def map_output_words(
    timeline: Timeline,
    plan: OutputPlan,
    segments: tuple[SemanticSegment, ...],
    asset_id: str,
    words: tuple[Word, ...],
) -> tuple[MappedWord, ...]:
    """Retain source Word IDs; (clip instance, Word ID) identifies an occurrence."""
    expected = compile_output_timeline(plan, segments, asset_id)
    if timeline.to_dict() != expected.to_dict():
        raise ValueError("subtitle timeline does not match its output plan")
    mapped: list[MappedWord] = []
    for clip in timeline.clips:
        # Reuse the existing strict mapper per occurrence. Its global duplicate
        # protection remains unchanged for the legacy keep/delete timeline.
        occurrence = Timeline((clip,), clip.output_range.end_ms)
        mapped.extend(map_retained_words(occurrence, segments, words))
    return tuple(mapped)
