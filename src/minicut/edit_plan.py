"""User editing brief and structured edit plan domain models."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import cast


class EditIntensity(StrEnum):
    """How aggressively removable content may be shortened."""

    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    AGGRESSIVE = "aggressive"


@dataclass(slots=True)
class ContentRequirement:
    """Natural-language content intent with optional resolved Segment IDs."""

    instruction: str
    segment_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.instruction.strip():
            raise ValueError("content requirement instruction must not be blank")
        if any(not segment_id.strip() for segment_id in self.segment_ids):
            raise ValueError("content requirement Segment IDs must not be blank")
        if len(set(self.segment_ids)) != len(self.segment_ids):
            raise ValueError("content requirement Segment IDs must be unique")

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""
        return {
            "instruction": self.instruction,
            "segment_ids": list(self.segment_ids),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "ContentRequirement":
        """Restore a content requirement from a JSON-compatible mapping."""
        return cls(
            instruction=cast(str, data["instruction"]),
            segment_ids=tuple(cast(list[str], data["segment_ids"])),
        )


@dataclass(slots=True)
class EditBrief:
    """User-owned goals and constraints for one edit plan."""

    target_duration_ms: int
    intensity: EditIntensity
    style: str
    content_type: str = "spoken_video"
    language: str = "auto"
    must_keep: tuple[ContentRequirement, ...] = ()
    must_remove: tuple[ContentRequirement, ...] = ()

    def __post_init__(self) -> None:
        if self.target_duration_ms <= 0:
            raise ValueError("target duration must be positive")
        if not self.style.strip():
            raise ValueError("edit style must not be blank")
        if not self.content_type.strip():
            raise ValueError("content type must not be blank")
        if not self.language.strip():
            raise ValueError("language must not be blank")

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""
        return {
            "target_duration_ms": self.target_duration_ms,
            "intensity": self.intensity.value,
            "style": self.style,
            "content_type": self.content_type,
            "language": self.language,
            "must_keep": [requirement.to_dict() for requirement in self.must_keep],
            "must_remove": [requirement.to_dict() for requirement in self.must_remove],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "EditBrief":
        """Restore an edit brief from a JSON-compatible mapping."""
        keep_data = cast(list[dict[str, object]], data["must_keep"])
        remove_data = cast(list[dict[str, object]], data["must_remove"])
        return cls(
            target_duration_ms=cast(int, data["target_duration_ms"]),
            intensity=EditIntensity(cast(str, data["intensity"])),
            style=cast(str, data["style"]),
            content_type=cast(str, data["content_type"]),
            language=cast(str, data["language"]),
            must_keep=tuple(
                ContentRequirement.from_dict(requirement) for requirement in keep_data
            ),
            must_remove=tuple(
                ContentRequirement.from_dict(requirement) for requirement in remove_data
            ),
        )


__all__ = ["ContentRequirement", "EditBrief", "EditIntensity"]
