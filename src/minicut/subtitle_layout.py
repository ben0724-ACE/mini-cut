"""Shared canvas geometry and font measurements for subtitle pages and ASS."""

from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache

from PIL import ImageFont

from minicut.output_plan import OutputPlan
from minicut.subtitle_font import SubtitleFont


@dataclass(frozen=True, slots=True)
class SubtitleGeometry:
    width: int
    height: int
    source_small: int
    source_large: int
    translation_small: int
    translation_large: int
    center_x: int
    bottom: int
    gap: int
    side: int
    translation_first: bool
    font: SubtitleFont | None = None

    @classmethod
    def for_output(
        cls,
        width: int,
        height: int,
        plan: OutputPlan | None = None,
        font: SubtitleFont | None = None,
    ) -> "SubtitleGeometry":
        if width <= 0 or height <= 0:
            raise ValueError("subtitle dimensions must be positive")
        portrait = width < height
        small = max(13, round(height * (0.033 if portrait else 0.042)))
        large = max(16, round(height * (0.041 if portrait else 0.055)))
        source_scale = plan.subtitle_source_scale if plan else 1
        translation_scale = plan.subtitle_translation_scale if plan else 1
        return cls(
            width,
            height,
            round(small * source_scale),
            round(large * source_scale),
            round(small * translation_scale),
            round(large * translation_scale),
            round(width * (plan.subtitle_horizontal_percent if plan else 50) / 100),
            round(
                height
                * (
                    plan.subtitle_bottom_percent
                    if plan
                    else (9.5 if portrait else 10.5)
                )
                / 100
            ),
            round(height * 0.022),
            round(width * 0.07),
            plan is not None and plan.subtitle_order == "translation_first",
            font,
        )

    @property
    def available_width(self) -> int:
        return max(
            1,
            2 * min(self.center_x - self.side, self.width - self.side - self.center_x),
        )

    def sizes(self, translation_language: str | None) -> tuple[int, int]:
        if translation_language == "zh":
            return self.source_small, self.translation_large
        return self.source_large, self.translation_small

    def measure(self, size: int) -> Callable[[str], float]:
        if self.font is not None:
            face = ImageFont.truetype(str(self.font.path), size)

            # libass may select a bold face; leave room for that and glyph outlines.
            @lru_cache(maxsize=2048)
            def measured_width(text: str) -> float:
                return float(face.getlength(text)) * 1.08

            return measured_width
        return lambda text: sum(size if ord(c) > 0x2FF else size * 0.6 for c in text)

    @staticmethod
    def row_height(size: int) -> int:
        return round(size * 1.25)
