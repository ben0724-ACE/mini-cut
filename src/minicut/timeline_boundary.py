"""Pure word-level boundary refinements for compiled timelines."""

from collections.abc import Mapping
from dataclasses import dataclass
from unicodedata import category

from minicut.media import TimeRange
from minicut.semantic_segment import SemanticSegment
from minicut.timeline import Clip, Timeline
from minicut.transcript import Word


@dataclass(frozen=True, slots=True)
class BoundaryPolicy:
    """Configurable source padding measured in integer milliseconds."""

    head_padding_ms: int = 0
    tail_padding_ms: int = 0

    def __post_init__(self) -> None:
        if self.head_padding_ms < 0 or self.tail_padding_ms < 0:
            raise ValueError("boundary padding must not be negative")


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
                clip.segment_ids,
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
                clip.segment_ids,
            )
        )
    return _reflow_clips(tuple(refined))


def snap_clip_end_boundaries(
    timeline: Timeline,
    segments: tuple[SemanticSegment, ...],
    words: tuple[Word, ...],
) -> Timeline:
    """Snap every clip end to its latest referenced Word end."""
    segments_by_id, words_by_id = _index_inputs(timeline, segments, words)
    refined: list[Clip] = []
    for clip in timeline.clips:
        segment = segments_by_id[clip.segment_id]
        last_word_end_ms = max(
            words_by_id[word_id].end_ms for word_id in segment.word_ids
        )
        refined.append(
            Clip(
                clip.clip_id,
                clip.source_asset_id,
                clip.segment_id,
                TimeRange(clip.source_range.start_ms, last_word_end_ms),
                clip.output_range,
                clip.segment_ids,
            )
        )
    return _reflow_clips(tuple(refined))


def apply_boundary_padding(
    timeline: Timeline,
    policy: BoundaryPolicy,
    media_duration_ms: int,
) -> Timeline:
    """Apply clamped source padding without overlapping adjacent clips."""
    if media_duration_ms <= 0:
        raise ValueError("media duration must be positive")
    for clip in timeline.clips:
        if clip.source_range.end_ms > media_duration_ms:
            raise ValueError("clip source range exceeds media duration")
    for previous, current in zip(timeline.clips, timeline.clips[1:], strict=False):
        if previous.source_range.end_ms > current.source_range.start_ms:
            raise ValueError("clip source ranges overlap before padding")

    padded_ranges = [
        TimeRange(
            max(0, clip.source_range.start_ms - policy.head_padding_ms),
            min(media_duration_ms, clip.source_range.end_ms + policy.tail_padding_ms),
        )
        for clip in timeline.clips
    ]
    for ordinal in range(1, len(padded_ranges)):
        previous = padded_ranges[ordinal - 1]
        current = padded_ranges[ordinal]
        if previous.end_ms <= current.start_ms:
            continue
        previous_source = timeline.clips[ordinal - 1].source_range
        current_source = timeline.clips[ordinal].source_range
        boundary_ms = (previous_source.end_ms + current_source.start_ms) // 2
        padded_ranges[ordinal - 1] = TimeRange(previous.start_ms, boundary_ms)
        padded_ranges[ordinal] = TimeRange(boundary_ms, current.end_ms)

    padded_clips = tuple(
        Clip(
            clip.clip_id,
            clip.source_asset_id,
            clip.segment_id,
            source_range,
            clip.output_range,
            clip.segment_ids,
        )
        for clip, source_range in zip(timeline.clips, padded_ranges, strict=True)
    )
    return _reflow_clips(padded_clips)


def _is_punctuation(text: str) -> bool:
    stripped = text.strip()
    return bool(stripped) and all(
        category(character).startswith("P") for character in stripped
    )


def protect_word_and_punctuation_boundaries(
    timeline: Timeline,
    segments: tuple[SemanticSegment, ...],
    words: tuple[Word, ...],
    media_duration_ms: int,
) -> Timeline:
    """Remove partial neighboring words and preserve owned words and punctuation."""
    if media_duration_ms <= 0:
        raise ValueError("media duration must be positive")
    segments_by_id, words_by_id = _index_inputs(timeline, segments, words)
    ordered_words = tuple(
        sorted(words, key=lambda word: (word.start_ms, word.end_ms, word.word_id))
    )
    owned_elsewhere = {word_id for segment in segments for word_id in segment.word_ids}
    refined: list[Clip] = []
    for clip in timeline.clips:
        segment = segments_by_id[clip.segment_id]
        owned_ids = set(segment.word_ids)
        start_ms = clip.source_range.start_ms
        end_ms = clip.source_range.end_ms

        start_words = tuple(
            word for word in ordered_words if word.start_ms < start_ms < word.end_ms
        )
        owned_start_words = tuple(
            word for word in start_words if word.word_id in owned_ids
        )
        if owned_start_words:
            start_ms = min(word.start_ms for word in owned_start_words)
        elif start_words:
            start_ms = max(word.end_ms for word in start_words)

        end_words = tuple(
            word for word in ordered_words if word.start_ms < end_ms < word.end_ms
        )
        owned_end_words = tuple(word for word in end_words if word.word_id in owned_ids)
        if owned_end_words:
            end_ms = max(word.end_ms for word in owned_end_words)
        elif end_words:
            end_ms = min(word.start_ms for word in end_words)

        last_owned_word = max(
            (words_by_id[word_id] for word_id in segment.word_ids),
            key=lambda word: (word.end_ms, word.start_ms, word.word_id),
        )
        if last_owned_word.end_ms <= end_ms:
            last_index = ordered_words.index(last_owned_word)
            for word in ordered_words[last_index + 1 :]:
                if not _is_punctuation(word.text) or word.word_id in owned_elsewhere:
                    break
                end_ms = max(end_ms, word.end_ms)

        refined.append(
            Clip(
                clip.clip_id,
                clip.source_asset_id,
                clip.segment_id,
                TimeRange(start_ms, end_ms),
                clip.output_range,
                clip.segment_ids,
            )
        )

    if any(clip.source_range.end_ms > media_duration_ms for clip in refined):
        raise ValueError("protected boundary exceeds media duration")
    for previous, current in zip(refined, refined[1:], strict=False):
        if previous.source_range.end_ms > current.source_range.start_ms:
            raise ValueError("protected boundaries overlap between adjacent clips")
    return _reflow_clips(tuple(refined))


__all__ = [
    "BoundaryPolicy",
    "apply_boundary_padding",
    "protect_word_and_punctuation_boundaries",
    "snap_clip_end_boundaries",
    "snap_clip_start_boundaries",
]
