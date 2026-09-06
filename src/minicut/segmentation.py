"""Deterministic transcript segmentation into utterances."""

from dataclasses import dataclass

from minicut.text_normalization import (
    ChineseScriptPolicy,
    TextNormalizationPolicy,
    WordTextMapping,
    normalize_text,
)
from minicut.transcript import Transcript, Utterance, Word, generate_utterance_id


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


def build_utterances_by_pause(
    transcript: Transcript,
    mappings: tuple[WordTextMapping, ...],
    *,
    policy: SegmentationPolicy | None = None,
) -> tuple[Utterance, ...]:
    """Group aligned transcript words whenever their gap stays below the threshold."""
    _validate_mapping_alignment(transcript, mappings)
    if not transcript.words:
        return ()

    selected_policy = policy if policy is not None else SegmentationPolicy()
    utterances: list[Utterance] = []
    group_start = 0
    for index in range(1, len(transcript.words)):
        previous = transcript.words[index - 1]
        current = transcript.words[index]
        if current.start_ms - previous.end_ms < selected_policy.pause_threshold_ms:
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


__all__ = ["SegmentationPolicy", "build_utterances_by_pause"]
