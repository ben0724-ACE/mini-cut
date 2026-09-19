"""Resolved preset defaults; explicit user requirements take precedence."""

import json
from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import cast


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
    preset_prompt: str | None = None
    body_mode: str = "continuous"

    def __post_init__(self) -> None:
        if self.body_mode not in {"continuous", "compact"}:
            raise ValueError("unsupported body mode")
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
        if self.preset_prompt is not None and (
            type(self.preset_prompt) is not str or not self.preset_prompt.strip()
        ):
            raise ValueError("preset prompt must be nonempty text")
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
            value = cls(preset, 3, 30000, 60000)
        else:
            value = cls(preset, 3, 60000, 90000)
        return replace(value, **overrides)

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        if self.preset_prompt is None:
            defaults = cast(
                dict[str, str],
                json.loads(
                    Path(__file__)
                    .with_name("preset_prompts.json")
                    .read_text(encoding="utf-8")
                ),
            )
            data["preset_prompt"] = defaults[self.preset.value]
        return data
