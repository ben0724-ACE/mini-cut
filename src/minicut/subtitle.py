"""Map retained transcript words onto rendered timeline time."""

from dataclasses import dataclass

from minicut.semantic_segment import SemanticSegment
from minicut.timeline import Timeline
from minicut.transcript import Word


@dataclass(frozen=True, slots=True)
class MappedWord:
    """One retained transcript token translated to output time."""

    word_id: str
    text: str
    start_ms: int
    end_ms: int
    clip_id: str

    def __post_init__(self) -> None:
        if not self.word_id.strip() or not self.clip_id.strip():
            raise ValueError("mapped Word and Clip IDs must not be blank")
        if self.start_ms < 0 or self.end_ms <= self.start_ms:
            raise ValueError("mapped Word time range must be non-empty")


def map_retained_words(
    timeline: Timeline,
    segments: tuple[SemanticSegment, ...],
    words: tuple[Word, ...],
) -> tuple[MappedWord, ...]:
    """Translate only retained Segment words from source to output time."""
    segments_by_id = {segment.segment_id: segment for segment in segments}
    words_by_id = {word.word_id: word for word in words}
    if len(segments_by_id) != len(segments):
        raise ValueError("Segment IDs must be unique for subtitle mapping")
    if len(words_by_id) != len(words):
        raise ValueError("Word IDs must be unique for subtitle mapping")

    mapped: list[MappedWord] = []
    mapped_word_ids: set[str] = set()
    for clip in timeline.clips:
        clip_word_ids: list[str] = []
        for segment_id in clip.segment_ids:
            segment = segments_by_id.get(segment_id)
            if segment is None:
                raise ValueError("Timeline Clip references an unknown Segment")
            clip_word_ids.extend(segment.word_ids)

        clip_words: list[Word] = []
        for word_id in dict.fromkeys(clip_word_ids):
            word = words_by_id.get(word_id)
            if word is None:
                raise ValueError("retained Segment references an unknown Word")
            if word_id in mapped_word_ids:
                raise ValueError("retained Word is mapped by more than one Clip")
            if (
                word.start_ms < clip.source_range.start_ms
                or word.end_ms > clip.source_range.end_ms
            ):
                raise ValueError("retained Word lies outside its Clip source range")
            clip_words.append(word)

        for word in sorted(
            clip_words,
            key=lambda item: (item.start_ms, item.end_ms, item.word_id),
        ):
            offset_ms = clip.output_range.start_ms - clip.source_range.start_ms
            mapped.append(
                MappedWord(
                    word.word_id,
                    word.text,
                    word.start_ms + offset_ms,
                    word.end_ms + offset_ms,
                    clip.clip_id,
                )
            )
            mapped_word_ids.add(word.word_id)
    return tuple(mapped)


__all__ = ["MappedWord", "map_retained_words"]
