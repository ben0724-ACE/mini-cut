"""Explicit-order compilation with validation bound to the source-ID plan."""

from minicut.media import MediaAsset, TimeRange
from minicut.output_plan import OutputPlan
from minicut.semantic_segment import (
    SemanticSegment,
    validate_segment_context_dependencies,
)
from minicut.timeline import Clip, Timeline
from minicut.timeline_validation import (
    TimelineDiagnosticSummary,
    TimelineTrackRequirements,
    TimelineValidationCode,
    TimelineValidationError,
    inspect_timeline_structure,
    inspect_timeline_tracks,
)


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
