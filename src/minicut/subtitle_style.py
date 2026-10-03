"""Saved subtitle typography in units of a 1080-pixel short-side canvas."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast


@dataclass(frozen=True, slots=True)
class SubtitleStyle:
    source_font_id: str | None = None
    translation_font_id: str | None = None
    source_size: int = 64
    translation_size: int = 48
    text_color: str = "#ffffff"
    bold: bool = True
    stroke_color: str = "#000000"
    stroke_width: int = 4
    shadow_color: str = "#000000"
    shadow_width: int = 0
    background_enabled: bool = False
    background_color: str = "#000000"
    background_opacity: int = 50

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "SubtitleStyle":
        values = dict(data)
        shared_font = values.pop("font_id", None)
        values.setdefault("source_font_id", shared_font)
        values.setdefault("translation_font_id", shared_font)
        return cls(**cast(dict[str, Any], values))

    def __post_init__(self) -> None:
        for font_id in (self.source_font_id, self.translation_font_id):
            if font_id is not None and not re.fullmatch(r"[a-z0-9_-]+", font_id):
                raise ValueError("invalid subtitle font ID")
        for size in (self.source_size, self.translation_size):
            if type(size) is not int or not 16 <= size <= 200:
                raise ValueError("字幕字号需为 16–200 的整数")
        for width in (self.stroke_width, self.shadow_width):
            if type(width) is not int or not 0 <= width <= 12:
                raise ValueError("描边和阴影宽度需为 0–12 的整数")
        for color in (
            self.text_color,
            self.stroke_color,
            self.shadow_color,
            self.background_color,
        ):
            if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
                raise ValueError("字幕颜色需为六位十六进制颜色")
        if type(self.bold) is not bool or type(self.background_enabled) is not bool:
            raise ValueError("subtitle effect switches must be boolean")
        if (
            type(self.background_opacity) is not int
            or not 0 <= self.background_opacity <= 100
        ):
            raise ValueError("背景不透明度需为 0–100 的整数")

    @staticmethod
    def scale(width: int, height: int) -> float:
        return min(width, height) / 1080
