"""Source-ID-based candidates and explicit per-video presentation order."""

import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import cast

from minicut.semantic_segment import (
    SemanticSegment,
    validate_segment_context_dependencies,
)


def validate_output_id(value: object) -> None:
    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_-]*", value
    ):
        raise ValueError("output/collection ID must be a safe local identifier")


def _text(value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("output text and references must not be blank")


def _unique(values: tuple[str, ...]) -> None:
    for value in values:
        _text(value)
    if len(set(values)) != len(values):
        raise ValueError("output identifiers must be unique")


class OutputRole(StrEnum):
    HOOK = "hook"
    BODY = "body"


@dataclass(frozen=True, slots=True)
class OutputItem:
    instance_id: str
    segment_id: str
    role: OutputRole

    def __post_init__(self) -> None:
        _text(self.instance_id)
        _text(self.segment_id)
        if type(self.role) is not OutputRole:
            raise ValueError("unsupported output role")


@dataclass(frozen=True, slots=True)
class HighlightCandidate:
    candidate_id: str
    title: str
    reason: str
    segment_ids: tuple[str, ...]
    context_segment_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for value in (self.candidate_id, self.title, self.reason):
            _text(value)
        if not self.segment_ids:
            raise ValueError("candidate must reference source segments")
        _unique(self.segment_ids)
        _unique(self.context_segment_ids)


@dataclass(frozen=True, slots=True)
class OutputPlan:
    output_id: str
    candidate_id: str
    title: str
    items: tuple[OutputItem, ...]
    revision: int = 1

    def __post_init__(self) -> None:
        validate_output_id(self.output_id)
        _text(self.candidate_id)
        _text(self.title)
        if not self.items:
            raise ValueError("output plan must contain items")
        _unique(tuple(item.instance_id for item in self.items))
        body_started = False
        seen_sources: set[tuple[OutputRole, str]] = set()
        for item in self.items:
            if item.role is OutputRole.BODY:
                body_started = True
            elif body_started:
                raise ValueError("hook items must precede the body")
            key = (item.role, item.segment_id)
            if key in seen_sources:
                raise ValueError("source reuse must be explicit across hook and body")
            seen_sources.add(key)
        if not body_started:
            raise ValueError("output plan requires a body")
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("output revision must be positive")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "OutputPlan":
        items = cast(list[Mapping[str, object]], data["items"])
        return cls(
            cast(str, data["output_id"]),
            cast(str, data["candidate_id"]),
            cast(str, data["title"]),
            tuple(
                OutputItem(
                    cast(str, item["instance_id"]),
                    cast(str, item["segment_id"]),
                    OutputRole(cast(str, item["role"])),
                )
                for item in items
            ),
            cast(int, data.get("revision", 1)),
        )


@dataclass(frozen=True, slots=True)
class OutputCollection:
    collection_id: str
    asset_id: str
    candidates: tuple[HighlightCandidate, ...]
    plans: tuple[OutputPlan, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        validate_output_id(self.collection_id)
        _text(self.asset_id)
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("unsupported OutputCollection schema version")
        if not self.candidates or not self.plans:
            raise ValueError("output collection must contain candidates and plans")
        _unique(tuple(candidate.candidate_id for candidate in self.candidates))
        _unique(tuple(plan.output_id for plan in self.plans))

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "OutputCollection":
        candidates = cast(list[Mapping[str, object]], data["candidates"])
        plans = cast(list[Mapping[str, object]], data["plans"])
        return cls(
            cast(str, data["collection_id"]),
            cast(str, data["asset_id"]),
            tuple(
                HighlightCandidate(
                    cast(str, item["candidate_id"]),
                    cast(str, item["title"]),
                    cast(str, item["reason"]),
                    tuple(cast(list[str], item["segment_ids"])),
                    tuple(cast(list[str], item.get("context_segment_ids", []))),
                )
                for item in candidates
            ),
            tuple(OutputPlan.from_dict(item) for item in plans),
            cast(int, data["schema_version"]),
        )


def validate_output_collection(
    collection: OutputCollection,
    segments: tuple[SemanticSegment, ...],
) -> None:
    validate_segment_context_dependencies(segments)
    source_ids = {segment.segment_id for segment in segments}
    candidates = {
        candidate.candidate_id: candidate for candidate in collection.candidates
    }
    for candidate in collection.candidates:
        if (
            not set((*candidate.segment_ids, *candidate.context_segment_ids))
            <= source_ids
        ):
            raise ValueError("candidate references unknown source IDs")
    for plan in collection.plans:
        candidate = candidates.get(plan.candidate_id)
        if candidate is None:
            raise ValueError("output references an unknown candidate")
        allowed = set((*candidate.segment_ids, *candidate.context_segment_ids))
        if not {item.segment_id for item in plan.items} <= allowed:
            raise ValueError("output references a source outside its candidate")
