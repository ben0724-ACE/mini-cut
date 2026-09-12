"""Resolved preset defaults; explicit user requirements take precedence."""

from dataclasses import asdict, dataclass, replace
from enum import StrEnum


class HighlightPreset(StrEnum):
    CLEAN_SPEECH = "clean_speech"
    PODCAST = "podcast_highlights"
    OPINION = "opinion_first"
    KNOWLEDGE = "knowledge_digest"


@dataclass(frozen=True, slots=True)
class HighlightBrief:
    preset: HighlightPreset
    count: int
    min_ms: int | None
    max_ms: int | None
    hook_ms: int | None = None
    instructions: str = ""
    max_source_overlap: float = 0.3

    def __post_init__(self) -> None:
        if type(self.preset) is not HighlightPreset:
            raise ValueError("unsupported highlight preset")
        if type(self.count) is not int or self.count < 1:
            raise ValueError("count must be positive")
        if (self.min_ms is None) != (self.max_ms is None):
            raise ValueError("duration range requires both limits")
        if self.min_ms is not None and self.max_ms is not None:
            if (
                any(type(v) is not int or v <= 0 for v in (self.min_ms, self.max_ms))
                or self.min_ms > self.max_ms
            ):
                raise ValueError("invalid duration range")
        if self.hook_ms is not None and (
            type(self.hook_ms) is not int or self.hook_ms <= 0
        ):
            raise ValueError("hook duration must be positive")
        if type(self.instructions) is not str:
            raise ValueError("instructions must be text")
        if not 0 <= self.max_source_overlap <= 1:
            raise ValueError("source overlap must be between zero and one")

    @classmethod
    def for_preset(
        cls, preset: HighlightPreset, **overrides: object
    ) -> "HighlightBrief":
        if preset is HighlightPreset.CLEAN_SPEECH:
            value = cls(preset, 1, None, None)
        elif preset is HighlightPreset.OPINION:
            value = cls(preset, 3, 30000, 60000, 5000)
        else:
            value = cls(preset, 3, 60000, 90000)
        return replace(value, **overrides)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
