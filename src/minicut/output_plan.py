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
    deleted: bool = False
    display_text: str | None = None
    source_start_ms: int | None = None
    source_end_ms: int | None = None
    translation_text: str | None = None
    translation_language: str | None = None
    subtitle_mode: str = "bilingual"

    def __post_init__(self) -> None:
        if self.translation_language not in {
            None,
            "zh",
            "en",
        } or self.subtitle_mode not in {"bilingual", "translated"}:
            raise ValueError("invalid translation settings")
        if self.translation_text is not None:
            _text(self.translation_text)
            if self.translation_language is None:
                raise ValueError("translation requires a target language")
        if (self.source_start_ms is None) != (self.source_end_ms is None):
            raise ValueError("Both source boundaries are required")
        if self.source_start_ms is not None and self.source_end_ms is not None:
            if (
                type(self.source_start_ms) is not int
                or type(self.source_end_ms) is not int
                or not 0 <= self.source_start_ms < self.source_end_ms
            ):
                raise ValueError("Invalid source boundaries")
        _text(self.instance_id)
        _text(self.segment_id)
        if type(self.role) is not OutputRole:
            raise ValueError("unsupported output role")
        if type(self.deleted) is not bool:
            raise ValueError("deleted must be boolean")
        if self.display_text is not None:
            _text(self.display_text)


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
    hook_transition_ms: int = 300
    hook_transition_kind: str = "fade"
    social_copy: str | None = None

    def __post_init__(self) -> None:
        if (
            type(self.hook_transition_ms) is not int
            or not 0 <= self.hook_transition_ms <= 1000
        ):
            raise ValueError("hook transition must be an integer between 0 and 1000 ms")
        if self.hook_transition_kind not in {"fade", "tv_static"}:
            raise ValueError("unsupported hook transition")
        validate_output_id(self.output_id)
        _text(self.candidate_id)
        _text(self.title)
        if self.social_copy is not None:
            _text(self.social_copy)
            if len(self.social_copy) > 2000:
                raise ValueError("social copy must not exceed 2000 characters")
        if not self.items:
            raise ValueError("output plan must contain items")
        _unique(tuple(item.instance_id for item in self.items))
        body_started = False
        seen_sources: dict[tuple[OutputRole, str], list[OutputItem]] = {}
        for item in self.items:
            if item.role is OutputRole.BODY:
                body_started = True
            elif body_started:
                raise ValueError("hook items must precede the body")
            key = (item.role, item.segment_id)
            for previous in seen_sources.get(key, []):
                if (
                    item.source_start_ms is None
                    or item.source_end_ms is None
                    or previous.source_start_ms is None
                    or previous.source_end_ms is None
                    or max(item.source_start_ms, previous.source_start_ms)
                    < min(item.source_end_ms, previous.source_end_ms)
                ):
                    raise ValueError(
                        "source reuse requires disjoint explicit sentence ranges"
                    )
            seen_sources.setdefault(key, []).append(item)
        if not body_started:
            raise ValueError("output plan requires a body")
        if not any(
            item.role is OutputRole.BODY and not item.deleted for item in self.items
        ):
            raise ValueError("output plan requires a retained body")
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
                    cast(bool, item.get("deleted", False)),
                    cast(str | None, item.get("display_text")),
                    cast(int | None, item.get("source_start_ms")),
                    cast(int | None, item.get("source_end_ms")),
                    cast(str | None, item.get("translation_text")),
                    cast(str | None, item.get("translation_language")),
                    cast(str, item.get("subtitle_mode", "bilingual")),
                )
                for item in items
            ),
            cast(int, data.get("revision", 1)),
            cast(int, data.get("hook_transition_ms", 300)),
            cast(str, data.get("hook_transition_kind", "fade")),
            cast(str | None, data.get("social_copy")),
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


def transition_gap_ms(plan: OutputPlan) -> int:
    if plan.hook_transition_kind == "tv_static" and any(
        item.role is OutputRole.HOOK and not item.deleted for item in plan.items
    ):
        return plan.hook_transition_ms
    return 0
