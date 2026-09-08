"""Pure word-level boundary refinements for compiled timelines."""

from collections.abc import Mapping

from minicut.media import TimeRange
from minicut.semantic_segment import SemanticSegment
from minicut.timeline import Clip, Timeline
from minicut.transcript import Word


def _index_inputs(
    timeline: Timeline,
    segments: tuple[SemanticSegment, ...],
    words: tuple[Word, ...],
) -> tuple[Mapping[str, SemanticSegment], Mapping[str, Word]]:
    segments_by_id = {segment.segment_id: segment for segment in segments}
    if len(segments_by_id) != len(segments):
        raise ValueError("Segment IDs must be unique")
    words_by_id = {word.word_id: word for word in words}
    if len(words_by_id) != len(words):
        raise ValueError("Word IDs must be unique")
    for clip in timeline.clips:
        segment = segments_by_id.get(clip.segment_id)
        if segment is None:
            raise ValueError("timeline clip references an unknown Segment")
        if any(word_id not in words_by_id for word_id in segment.word_ids):
            raise ValueError("Segment references an unknown Word")
    return segments_by_id, words_by_id


def _reflow_clips(clips: tuple[Clip, ...]) -> Timeline:
    reflowed: list[Clip] = []
    output_cursor_ms = 0
    for clip in clips:
        output_end_ms = output_cursor_ms + clip.source_range.duration_ms
        reflowed.append(
            Clip(
                clip.clip_id,
                clip.source_asset_id,
                clip.segment_id,
                clip.source_range,
                TimeRange(output_cursor_ms, output_end_ms),
            )
        )
        output_cursor_ms = output_end_ms
    return Timeline(tuple(reflowed), output_cursor_ms)


def snap_clip_start_boundaries(
    timeline: Timeline,
    segments: tuple[SemanticSegment, ...],
    words: tuple[Word, ...],
) -> Timeline:
    """Snap every clip start to its earliest referenced Word start."""
    segments_by_id, words_by_id = _index_inputs(timeline, segments, words)
    refined: list[Clip] = []
    for clip in timeline.clips:
        segment = segments_by_id[clip.segment_id]
        first_word_start_ms = min(
            words_by_id[word_id].start_ms for word_id in segment.word_ids
        )
        refined.append(
            Clip(
                clip.clip_id,
                clip.source_asset_id,
                clip.segment_id,
                TimeRange(first_word_start_ms, clip.source_range.end_ms),
                clip.output_range,
            )
        )
    return _reflow_clips(tuple(refined))


__all__ = ["snap_clip_start_boundaries"]
