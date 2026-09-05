"""Normalized transcript domain models."""

from dataclasses import dataclass
from itertools import pairwise

TRANSCRIPT_SCHEMA_VERSION = 1


def _validate_time_range(label: str, start_ms: int, end_ms: int) -> None:
    if start_ms < 0 or end_ms <= start_ms:
        raise ValueError(
            f"{label} time range must have a non-negative start and later end"
        )


@dataclass(slots=True)
class Word:
    """One timestamped word or token from normalized transcription."""

    word_id: str
    text: str
    start_ms: int
    end_ms: int
    probability: float | None = None

    def __post_init__(self) -> None:
        _validate_time_range("Word", self.start_ms, self.end_ms)
        if self.probability is not None and not 0.0 <= self.probability <= 1.0:
            raise ValueError("probability must be between zero and one")


@dataclass(slots=True)
class Utterance:
    """One continuous span of speech referencing normalized words."""

    utterance_id: str
    text: str
    start_ms: int
    end_ms: int
    word_ids: tuple[str, ...]
    speaker: str | None = None

    def __post_init__(self) -> None:
        _validate_time_range("Utterance", self.start_ms, self.end_ms)


@dataclass(slots=True)
class TranscriptSource:
    """Media and transcription implementation used to produce a transcript."""

    asset_id: str
    provider: str
    model: str


@dataclass(slots=True)
class Transcript:
    """Versioned normalized transcript for one media asset."""

    transcript_id: str
    source: TranscriptSource
    language: str
    words: tuple[Word, ...] = ()
    utterances: tuple[Utterance, ...] = ()
    schema_version: int = TRANSCRIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for previous, current in pairwise(self.words):
            if current.start_ms < previous.start_ms or current.end_ms < previous.end_ms:
                raise ValueError("Word timestamps must be monotonic")

        words_by_id = {word.word_id: word for word in self.words}
        for utterance in self.utterances:
            for word_id in utterance.word_ids:
                word = words_by_id.get(word_id)
                if word is None:
                    raise ValueError(f"Utterance references unknown Word ID: {word_id}")
                if word.start_ms < utterance.start_ms or word.end_ms > utterance.end_ms:
                    raise ValueError("Utterance must contain each referenced Word")


__all__ = [
    "TRANSCRIPT_SCHEMA_VERSION",
    "Transcript",
    "TranscriptSource",
    "Utterance",
    "Word",
]
