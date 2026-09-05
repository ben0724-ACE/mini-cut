"""Normalized transcript domain models."""

from dataclasses import dataclass

TRANSCRIPT_SCHEMA_VERSION = 1


@dataclass(slots=True)
class Word:
    """One timestamped word or token from normalized transcription."""

    word_id: str
    text: str
    start_ms: int
    end_ms: int
    probability: float | None = None

    def __post_init__(self) -> None:
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


__all__ = [
    "TRANSCRIPT_SCHEMA_VERSION",
    "Transcript",
    "TranscriptSource",
    "Utterance",
    "Word",
]
