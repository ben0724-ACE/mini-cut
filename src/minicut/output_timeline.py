"""Explicit-order compilation with validation bound to the source-ID plan."""

from dataclasses import dataclass, replace
from textwrap import wrap

from minicut.media import MediaAsset, TimeRange
from minicut.output_plan import OutputPlan, OutputRole, transition_gap_ms
from minicut.semantic_segment import (
    ContextDirection,
    SemanticSegment,
    validate_segment_context_dependencies,
)
from minicut.subtitle import (
    MappedWord,
    SubtitleCue,
    SubtitleLayoutPolicy,
    build_readable_cues,
    map_retained_words,
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
    gap_added = False
    for item in plan.items:
        if item.deleted:
            continue
        if item.role is OutputRole.BODY and not gap_added:
            cursor += transition_gap_ms(plan)
            gap_added = True
        segment = by_id.get(item.segment_id)
        if segment is None:
            raise ValueError("output references an unknown source segment")
        source = TimeRange(
            segment.start_ms if item.source_start_ms is None else item.source_start_ms,
            segment.end_ms if item.source_end_ms is None else item.source_end_ms,
        )
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
    if transition_gap_ms(plan):
        # Exact plan compilation above permits only its deliberate effect interval.
        intentional.add(TimelineValidationCode.OUTPUT_DISCONTINUITY)
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
        if item.deleted:
            continue
        segment = by_id.get(item.segment_id)
        if segment is None:
            raise ValueError("output references an unknown source segment")
        for dependency in segment.context_dependencies:
            positions = [
                position
                for position, other in enumerate(plan.items)
                if not other.deleted
                and other.role is item.role
                and other.segment_id == dependency.segment_id
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
    by_instance = {item.instance_id: item for item in plan.items}
    for clip in timeline.clips:
        if by_instance[clip.clip_id].source_start_ms is not None:
            # User-approved boundaries can extend beyond the original AI segment.
            # Keep source word identities and clip intersecting words to that range.
            offset = clip.output_range.start_ms - clip.source_range.start_ms
            for word in words:
                start = max(word.start_ms, clip.source_range.start_ms)
                end = min(word.end_ms, clip.source_range.end_ms)
                if start < end:
                    mapped.append(
                        MappedWord(
                            word.word_id,
                            word.text,
                            start + offset,
                            end + offset,
                            clip.clip_id,
                        )
                    )
            continue
        # Reuse the existing strict mapper per occurrence. Its global duplicate
        # protection remains unchanged for the legacy keep/delete timeline.
        occurrence = Timeline((clip,), clip.output_range.end_ms)
        mapped.extend(map_retained_words(occurrence, segments, words))
    return tuple(mapped)


_DEFAULT_SUBTITLE_POLICY = SubtitleLayoutPolicy()


def build_output_cues(
    timeline: Timeline,
    plan: OutputPlan,
    mapped: tuple[MappedWord, ...],
    policy: SubtitleLayoutPolicy = _DEFAULT_SUBTITLE_POLICY,
) -> tuple[SubtitleCue, ...]:
    by_instance = {item.instance_id: item for item in plan.items}
    cues: list[SubtitleCue] = []
    for clip in timeline.clips:
        item = by_instance[clip.clip_id]
        if item.display_text is not None:
            lines = wrap(item.display_text, width=policy.max_characters_per_line)
            pages = [
                "\n".join(lines[n : n + policy.max_lines])
                for n in range(0, len(lines), policy.max_lines)
            ]
            total = sum(len(page) for page in pages)
            consumed = 0
            for page in pages:
                start = (
                    clip.output_range.start_ms
                    + clip.output_range.duration_ms * consumed // total
                )
                consumed += len(page)
                end = (
                    clip.output_range.start_ms
                    + clip.output_range.duration_ms * consumed // total
                )
                if end > start:
                    cues.append(SubtitleCue(start, end, page))
        else:
            cues.extend(
                build_readable_cues(
                    tuple(word for word in mapped if word.clip_id == clip.clip_id),
                    clip.output_range.end_ms,
                    policy,
                )
            )
    return tuple(cues)


def coalesce_output_media(timeline: Timeline, plan: OutputPlan) -> Timeline:
    """Sentence editing boundaries must not introduce media cuts or audio fades."""
    roles = {item.instance_id: item.role for item in plan.items}
    clips: list[Clip] = []
    for clip in timeline.clips:
        if clips and (
            clips[-1].source_asset_id == clip.source_asset_id
            and roles[clips[-1].clip_id] is roles[clip.clip_id]
            and clips[-1].source_range.end_ms == clip.source_range.start_ms
            and clips[-1].output_range.end_ms == clip.output_range.start_ms
        ):
            previous = clips[-1]
            clips[-1] = replace(
                previous,
                source_range=TimeRange(
                    previous.source_range.start_ms, clip.source_range.end_ms
                ),
                output_range=TimeRange(
                    previous.output_range.start_ms, clip.output_range.end_ms
                ),
            )
        else:
            clips.append(clip)
    return Timeline(tuple(clips), timeline.estimated_duration_ms)
