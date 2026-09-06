"""Deterministic transcript segmentation into utterances."""

from dataclasses import dataclass

from minicut.text_normalization import (
    ChineseScriptPolicy,
    TextNormalizationPolicy,
    WordTextMapping,
    normalize_text,
)
from minicut.transcript import Transcript, Utterance, Word, generate_utterance_id

_TERMINAL_PUNCTUATION = "。！？.!?"


@dataclass(slots=True)
class SegmentationPolicy:
    """Tunable timing boundaries for utterance and segment construction."""

    pause_threshold_ms: int = 800
    min_duration_ms: int = 1_000
    max_duration_ms: int = 15_000

    def __post_init__(self) -> None:
        if self.pause_threshold_ms <= 0:
            raise ValueError("pause threshold must be positive")
        if self.min_duration_ms <= 0:
            raise ValueError("minimum duration must be positive")
        if self.max_duration_ms < self.min_duration_ms:
            raise ValueError(
                "maximum duration must not be shorter than minimum duration"
            )


def _validate_mapping_alignment(
    transcript: Transcript,
    mappings: tuple[WordTextMapping, ...],
) -> None:
    word_identity = tuple((word.word_id, word.text) for word in transcript.words)
    mapping_identity = tuple(
        (mapping.word_id, mapping.raw_text) for mapping in mappings
    )
    if mapping_identity != word_identity:
        raise ValueError("word text mappings must align with transcript words")


def _build_utterance(
    transcript_id: str,
    ordinal: int,
    words: tuple[Word, ...],
    mappings: tuple[WordTextMapping, ...],
) -> Utterance:
    word_ids = tuple(word.word_id for word in words)
    text = normalize_text(
        " ".join(
            mapping.normalized_text for mapping in mappings if mapping.normalized_text
        ),
        policy=TextNormalizationPolicy(chinese_script=ChineseScriptPolicy.PRESERVE),
    )
    start_ms = words[0].start_ms
    end_ms = words[-1].end_ms
    return Utterance(
        utterance_id=generate_utterance_id(
            transcript_id,
            ordinal,
            text=text,
            start_ms=start_ms,
            end_ms=end_ms,
            word_ids=word_ids,
        ),
        text=text,
        start_ms=start_ms,
        end_ms=end_ms,
        word_ids=word_ids,
    )


def _contains_cjk(text: str) -> bool:
    return any(
        "\u3400" <= character <= "\u4dbf"
        or "\u4e00" <= character <= "\u9fff"
        or "\uf900" <= character <= "\ufaff"
        for character in text
    )


def _contains_western_word_character(text: str) -> bool:
    return any(character.isascii() and character.isalnum() for character in text)


def _is_mixed_language_boundary(left: str, right: str) -> bool:
    return (_contains_cjk(left) and _contains_western_word_character(right)) or (
        _contains_western_word_character(left) and _contains_cjk(right)
    )


def _span_duration_ms(words: tuple[Word, ...], span: tuple[int, int]) -> int:
    start, end = span
    return words[end - 1].end_ms - words[start].start_ms


def _can_merge_spans(
    words: tuple[Word, ...],
    left: tuple[int, int],
    right: tuple[int, int],
    policy: SegmentationPolicy,
) -> bool:
    gap_ms = words[right[0]].start_ms - words[left[1] - 1].end_ms
    merged_duration_ms = words[right[1] - 1].end_ms - words[left[0]].start_ms
    return (
        gap_ms < policy.pause_threshold_ms
        and merged_duration_ms <= policy.max_duration_ms
    )


def _merge_short_spans(
    words: tuple[Word, ...],
    spans: list[tuple[int, int]],
    policy: SegmentationPolicy,
) -> list[tuple[int, int]]:
    index = 0
    while index < len(spans):
        if _span_duration_ms(words, spans[index]) >= policy.min_duration_ms:
            index += 1
            continue

        candidates: list[tuple[int, int]] = []
        if index > 0 and _can_merge_spans(
            words, spans[index - 1], spans[index], policy
        ):
            previous_gap = (
                words[spans[index][0]].start_ms - words[spans[index - 1][1] - 1].end_ms
            )
            candidates.append((previous_gap, index - 1))
        if index + 1 < len(spans) and _can_merge_spans(
            words, spans[index], spans[index + 1], policy
        ):
            next_gap = (
                words[spans[index + 1][0]].start_ms - words[spans[index][1] - 1].end_ms
            )
            candidates.append((next_gap, index))

        if not candidates:
            index += 1
            continue

        _, left_index = min(candidates)
        left = spans[left_index]
        right = spans[left_index + 1]
        spans[left_index] = (left[0], right[1])
        del spans[left_index + 1]
        index = max(0, left_index - 1)

    return spans


def _build_utterances(
    transcript: Transcript,
    mappings: tuple[WordTextMapping, ...],
    *,
    policy: SegmentationPolicy,
    include_text_boundaries: bool,
) -> tuple[Utterance, ...]:
    _validate_mapping_alignment(transcript, mappings)
    if not transcript.words:
        return ()

    spans: list[tuple[int, int]] = []
    group_start = 0
    pending_boundary = False
    for index in range(1, len(transcript.words)):
        previous = transcript.words[index - 1]
        current = transcript.words[index]
        pause_boundary = current.start_ms - previous.end_ms >= policy.pause_threshold_ms
        terminal_boundary = (
            include_text_boundaries
            and mappings[index - 1].normalized_text[-1:] in _TERMINAL_PUNCTUATION
        )
        duration_boundary = (
            include_text_boundaries
            and current.end_ms - transcript.words[group_start].start_ms
            > policy.max_duration_ms
        )
        boundary_requested = pause_boundary or terminal_boundary or duration_boundary
        if current.start_ms < previous.end_ms:
            pending_boundary = pending_boundary or boundary_requested
            continue
        if not (pending_boundary or boundary_requested):
            continue

        boundary_index = index
        if (
            duration_boundary
            and not pause_boundary
            and not terminal_boundary
            and index - group_start >= 2
            and _is_mixed_language_boundary(
                mappings[index - 1].normalized_text,
                mappings[index].normalized_text,
            )
        ):
            boundary_index -= 1

        spans.append((group_start, boundary_index))
        group_start = boundary_index
        pending_boundary = False

    spans.append((group_start, len(transcript.words)))
    if include_text_boundaries:
        spans = _merge_short_spans(transcript.words, spans, policy)

    return tuple(
        _build_utterance(
            transcript.transcript_id,
            ordinal,
            transcript.words[start:end],
            mappings[start:end],
        )
        for ordinal, (start, end) in enumerate(spans)
    )


def build_utterances_by_pause(
    transcript: Transcript,
    mappings: tuple[WordTextMapping, ...],
    *,
    policy: SegmentationPolicy | None = None,
) -> tuple[Utterance, ...]:
    """Group aligned transcript words using pause boundaries only."""
    return _build_utterances(
        transcript,
        mappings,
        policy=policy if policy is not None else SegmentationPolicy(),
        include_text_boundaries=False,
    )


def build_utterances(
    transcript: Transcript,
    mappings: tuple[WordTextMapping, ...],
    *,
    policy: SegmentationPolicy | None = None,
) -> tuple[Utterance, ...]:
    """Build utterances from pause, terminal punctuation, and duration boundaries."""
    return _build_utterances(
        transcript,
        mappings,
        policy=policy if policy is not None else SegmentationPolicy(),
        include_text_boundaries=True,
    )


__all__ = [
    "SegmentationPolicy",
    "build_utterances",
    "build_utterances_by_pause",
]
