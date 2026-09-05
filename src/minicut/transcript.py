"""Normalized transcript domain models."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from itertools import pairwise
from typing import cast

TRANSCRIPT_SCHEMA_VERSION = 1


def _validate_schema_version(schema_version: object) -> None:
    if type(schema_version) is not int or schema_version != TRANSCRIPT_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported Transcript schema version: {schema_version}. "
            f"Migrate this data to schema version {TRANSCRIPT_SCHEMA_VERSION} "
            "before loading."
        )


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

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""
        return {
            "word_id": self.word_id,
            "text": self.text,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "probability": self.probability,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "Word":
        """Restore a Word from a JSON-compatible mapping."""
        return cls(
            word_id=cast(str, data["word_id"]),
            text=cast(str, data["text"]),
            start_ms=cast(int, data["start_ms"]),
            end_ms=cast(int, data["end_ms"]),
            probability=cast(float | None, data["probability"]),
        )


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

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""
        return {
            "utterance_id": self.utterance_id,
            "text": self.text,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "word_ids": list(self.word_ids),
            "speaker": self.speaker,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "Utterance":
        """Restore an Utterance from a JSON-compatible mapping."""
        return cls(
            utterance_id=cast(str, data["utterance_id"]),
            text=cast(str, data["text"]),
            start_ms=cast(int, data["start_ms"]),
            end_ms=cast(int, data["end_ms"]),
            word_ids=tuple(cast(list[str], data["word_ids"])),
            speaker=cast(str | None, data["speaker"]),
        )


@dataclass(slots=True)
class TranscriptSource:
    """Media and transcription implementation used to produce a transcript."""

    asset_id: str
    provider: str
    model: str

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""
        return {
            "asset_id": self.asset_id,
            "provider": self.provider,
            "model": self.model,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "TranscriptSource":
        """Restore a TranscriptSource from a JSON-compatible mapping."""
        return cls(
            asset_id=cast(str, data["asset_id"]),
            provider=cast(str, data["provider"]),
            model=cast(str, data["model"]),
        )


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
        _validate_schema_version(self.schema_version)
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

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""
        return {
            "schema_version": self.schema_version,
            "transcript_id": self.transcript_id,
            "source": self.source.to_dict(),
            "language": self.language,
            "words": [word.to_dict() for word in self.words],
            "utterances": [utterance.to_dict() for utterance in self.utterances],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "Transcript":
        """Restore a Transcript from a JSON-compatible mapping."""
        schema_version = data["schema_version"]
        _validate_schema_version(schema_version)
        source_data = cast(dict[str, object], data["source"])
        word_data = cast(list[dict[str, object]], data["words"])
        utterance_data = cast(list[dict[str, object]], data["utterances"])
        return cls(
            transcript_id=cast(str, data["transcript_id"]),
            source=TranscriptSource.from_dict(source_data),
            language=cast(str, data["language"]),
            words=tuple(Word.from_dict(word) for word in word_data),
            utterances=tuple(
                Utterance.from_dict(utterance) for utterance in utterance_data
            ),
            schema_version=cast(int, schema_version),
        )


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
