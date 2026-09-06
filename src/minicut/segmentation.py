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

    utterances: list[Utterance] = []
    group_start = 0
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
        if not (pause_boundary or terminal_boundary or duration_boundary):
            continue

        utterances.append(
            _build_utterance(
                transcript.transcript_id,
                len(utterances),
                transcript.words[group_start:index],
                mappings[group_start:index],
            )
        )
        group_start = index

    utterances.append(
        _build_utterance(
            transcript.transcript_id,
            len(utterances),
            transcript.words[group_start:],
            mappings[group_start:],
        )
    )
    return tuple(utterances)


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
