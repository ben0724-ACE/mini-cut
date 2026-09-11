"""Anonymous, JSON-compatible reference samples for edit-quality evaluation."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

EVAL_SAMPLE_SCHEMA_VERSION = 1


class EvalScenario(StrEnum):
    """Representative spoken-video conditions covered by the evaluation set."""

    FLUENT = "fluent"
    PAUSE_HEAVY = "pause_heavy"
    FALSE_STARTS = "false_starts"
    REPETITION_HEAVY = "repetition_heavy"
    MIXED_LANGUAGE = "mixed_language"


class ReferenceAction(StrEnum):
    """Human reference decision for one independently editable segment."""

    KEEP = "keep"
    DELETE = "delete"


class EvalLabel(StrEnum):
    """Human labels used to explain and later score a reference decision."""

    CORE_CONTENT = "core_content"
    OPTIONAL_CONTENT = "optional_content"
    FILLER = "filler"
    FALSE_START = "false_start"
    REPETITION = "repetition"
    NARRATIVE_DEPENDENCY = "narrative_dependency"


def _validate_opaque_id(value: str, field: str) -> None:
    if not value or any(
        character
        not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
        for character in value
    ):
        raise ValueError(f"{field} must be an opaque identifier, not a path")


@dataclass(frozen=True, slots=True)
class EvalWord:
    word_id: str
    text: str
    start_ms: int
    end_ms: int

    def __post_init__(self) -> None:
        _validate_opaque_id(self.word_id, "word ID")
        if not self.text.strip():
            raise ValueError("evaluation word text must not be blank")
        if self.start_ms < 0 or self.end_ms <= self.start_ms:
            raise ValueError("evaluation word time range is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "word_id": self.word_id,
            "text": self.text,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "EvalWord":
        return cls(
            cast(str, data["word_id"]),
            cast(str, data["text"]),
            cast(int, data["start_ms"]),
            cast(int, data["end_ms"]),
        )


@dataclass(frozen=True, slots=True)
class EvalSegment:
    segment_id: str
    word_ids: tuple[str, ...]
    reference_action: ReferenceAction
    labels: tuple[EvalLabel, ...]
    required_context_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_opaque_id(self.segment_id, "segment ID")
        if not self.word_ids or len(set(self.word_ids)) != len(self.word_ids):
            raise ValueError("evaluation segment word IDs must be non-empty and unique")
        if not self.labels or len(set(self.labels)) != len(self.labels):
            raise ValueError("evaluation segment labels must be non-empty and unique")
        if len(set(self.required_context_ids)) != len(self.required_context_ids):
            raise ValueError("required context IDs must be unique")
        if self.segment_id in self.required_context_ids:
            raise ValueError("evaluation segment cannot require itself")

    def to_dict(self) -> dict[str, object]:
        return {
            "segment_id": self.segment_id,
            "word_ids": list(self.word_ids),
            "reference_action": self.reference_action.value,
            "labels": [label.value for label in self.labels],
            "required_context_ids": list(self.required_context_ids),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "EvalSegment":
        return cls(
            cast(str, data["segment_id"]),
            tuple(cast(list[str], data["word_ids"])),
            ReferenceAction(cast(str, data["reference_action"])),
            tuple(EvalLabel(value) for value in cast(list[str], data["labels"])),
            tuple(cast(list[str], data.get("required_context_ids", []))),
        )


@dataclass(frozen=True, slots=True)
class EvalSample:
    """One anonymized transcript plus human reference decisions."""

    sample_id: str
    media_id: str
    scenario: EvalScenario
    language: str
    words: tuple[EvalWord, ...]
    segments: tuple[EvalSegment, ...]
    schema_version: int = EVAL_SAMPLE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _validate_opaque_id(self.sample_id, "sample ID")
        _validate_opaque_id(self.media_id, "media ID")
        if not self.language.strip():
            raise ValueError("evaluation language must not be blank")
        if self.schema_version != EVAL_SAMPLE_SCHEMA_VERSION:
            raise ValueError("unsupported evaluation sample schema version")
        word_ids = tuple(word.word_id for word in self.words)
        segment_ids = tuple(segment.segment_id for segment in self.segments)
        if not word_ids or len(set(word_ids)) != len(word_ids):
            raise ValueError("evaluation word IDs must be non-empty and unique")
        if not segment_ids or len(set(segment_ids)) != len(segment_ids):
            raise ValueError("evaluation segment IDs must be non-empty and unique")
        referenced_words = tuple(
            word_id for segment in self.segments for word_id in segment.word_ids
        )
        if len(set(referenced_words)) != len(referenced_words):
            raise ValueError("evaluation words must belong to exactly one segment")
        if set(referenced_words) != set(word_ids):
            raise ValueError("evaluation segments must cover every transcript word")
        known_segments = set(segment_ids)
        if any(
            context_id not in known_segments
            for segment in self.segments
            for context_id in segment.required_context_ids
        ):
            raise ValueError("required context references an unknown segment")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "sample_id": self.sample_id,
            "media_id": self.media_id,
            "scenario": self.scenario.value,
            "language": self.language,
            "words": [word.to_dict() for word in self.words],
            "segments": [segment.to_dict() for segment in self.segments],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "EvalSample":
        return cls(
            sample_id=cast(str, data["sample_id"]),
            media_id=cast(str, data["media_id"]),
            scenario=EvalScenario(cast(str, data["scenario"])),
            language=cast(str, data["language"]),
            words=tuple(
                EvalWord.from_dict(item)
                for item in cast(list[dict[str, object]], data["words"])
            ),
            segments=tuple(
                EvalSegment.from_dict(item)
                for item in cast(list[dict[str, object]], data["segments"])
            ),
            schema_version=cast(int, data["schema_version"]),
        )


__all__ = [
    "EVAL_SAMPLE_SCHEMA_VERSION",
    "EvalLabel",
    "EvalSample",
    "EvalScenario",
    "EvalSegment",
    "EvalWord",
    "ReferenceAction",
]
