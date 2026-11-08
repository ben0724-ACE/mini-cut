"""Saved, source-bound introductory cards; no model or network dependency."""

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from minicut.errors import UserInputError

if TYPE_CHECKING:
    from minicut.output_plan import OutputItem, OutputPlan
    from minicut.semantic_segment import SemanticSegment


@dataclass(frozen=True, slots=True)
class IntroSettings:
    title: str
    text: str = ""
    duration_ms: int = 5000
    frame_ms: int | None = None
    music: bool = True
    motion: bool = True
    font_id: str | None = None
    motion_style: str = "rise"
    music_version: int = 2
    motion_strength: float = 1.0
    transition_ms: int = 600
    audio_id: str | None = None

    def __post_init__(self) -> None:
        if type(self.title) is not str or not self.title.strip():
            raise ValueError("导读标题不能为空")
        if len(self.title) > 80 or type(self.text) is not str or len(self.text) > 180:
            raise ValueError("导读标题最多 80 字，介绍最多 180 字，请精简后保存")
        if type(self.duration_ms) is not int or not 2000 <= self.duration_ms <= 15000:
            raise ValueError("导读时长须为 2–15 秒")
        if self.frame_ms is not None and (
            type(self.frame_ms) is not int or self.frame_ms < 0
        ):
            raise ValueError("导读背景时间无效")
        if type(self.music) is not bool:
            raise ValueError("导读音乐开关无效")
        if type(self.motion) is not bool:
            raise ValueError("导读动效开关无效")
        if self.font_id is not None and not re.fullmatch(
            r"[a-z0-9_-]{1,512}", self.font_id
        ):
            raise ValueError("导读字体无效")
        if self.motion_style not in {"fade", "rise"}:
            raise ValueError("导读动效样式无效")
        if type(self.music_version) is not int or self.music_version not in {1, 2}:
            raise ValueError("导读配乐方案无效")
        if (
            type(self.motion_strength) not in {int, float}
            or not math.isfinite(self.motion_strength)
            or not 0 <= self.motion_strength <= 2
        ):
            raise ValueError("导读动效强度须为 0–200%")
        if type(self.transition_ms) is not int or not 0 <= self.transition_ms <= 1500:
            raise ValueError("导读黑场转场须为 0–1500 毫秒")
        if self.audio_id is not None and not re.fullmatch(
            r"[a-f0-9]{32}", self.audio_id
        ):
            raise ValueError("自定义 BGM 标识无效")

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "IntroSettings":
        return cls(
            cast(str, data["title"]),
            cast(str, data.get("text", "")),
            cast(int, data.get("duration_ms", 5000)),
            cast(int | None, data.get("frame_ms")),
            cast(bool, data.get("music", True)),
            cast(bool, data.get("motion", False)),
            cast(str | None, data.get("font_id")),
            cast(str, data.get("motion_style", "fade")),
            2,  # The legacy score has been removed; keep its stored field readable.
            cast(float, data.get("motion_strength", 1.0)),
            cast(int, data.get("transition_ms", 0)),
            cast(str | None, data.get("audio_id")),
        )


def intro_frame_ms(plan: "OutputPlan", segments: tuple["SemanticSegment", ...]) -> int:
    """Resolve a still only within retained source media, including explicit edits."""
    by_id = {segment.segment_id: segment for segment in segments}
    retained = [item for item in plan.items if not item.deleted]
    first = next(item for item in retained if item.role == "body")

    def bounds(item: "OutputItem") -> tuple[int, int]:
        segment = by_id[item.segment_id]
        return (
            segment.start_ms if item.source_start_ms is None else item.source_start_ms,
            segment.end_ms if item.source_end_ms is None else item.source_end_ms,
        )

    selected = plan.intro.frame_ms if plan.intro else None
    selected = bounds(first)[0] if selected is None else selected
    if not any(start <= selected < end for start, end in map(bounds, retained)):
        raise UserInputError("导读背景帧不在当前保留片段内，请重新选择或恢复默认帧")
    return selected
