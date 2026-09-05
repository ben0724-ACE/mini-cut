"""Normalized transcript domain models."""

import json
from dataclasses import dataclass
from hashlib import sha256
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


def _stable_id(kind: str, *components: object) -> str:
    normalized = json.dumps(
        [kind, *components],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"{kind}:{sha256(normalized).hexdigest()}"


def _validate_ordinal(ordinal: int) -> None:
    if ordinal < 0:
        raise ValueError("ordinal must not be negative")


def generate_transcript_id(source: TranscriptSource, language: str) -> str:
    """Generate a stable transcript ID from its normalized source identity."""
    return _stable_id(
        "transcript",
        source.asset_id,
        source.provider,
        source.model,
        language,
    )


def generate_word_id(
    transcript_id: str,
    ordinal: int,
    *,
    text: str,
    start_ms: int,
    end_ms: int,
) -> str:
    """Generate a stable Word ID from normalized word fields."""
    _validate_ordinal(ordinal)
    return _stable_id("word", transcript_id, ordinal, text, start_ms, end_ms)


def generate_utterance_id(
    transcript_id: str,
    ordinal: int,
    *,
    text: str,
    start_ms: int,
    end_ms: int,
    word_ids: tuple[str, ...],
    speaker: str | None = None,
) -> str:
    """Generate a stable Utterance ID from normalized utterance fields."""
    _validate_ordinal(ordinal)
    return _stable_id(
        "utterance",
        transcript_id,
        ordinal,
        text,
        start_ms,
        end_ms,
        word_ids,
        speaker,
    )


__all__ = [
    "TRANSCRIPT_SCHEMA_VERSION",
    "Transcript",
    "TranscriptSource",
    "Utterance",
    "Word",
    "generate_transcript_id",
    "generate_utterance_id",
    "generate_word_id",
]
