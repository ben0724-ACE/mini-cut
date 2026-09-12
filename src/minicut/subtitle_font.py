"""Explicit local fonts for burned subtitles; never download or bundle fonts."""

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from minicut.errors import UserInputError


@dataclass(frozen=True, slots=True)
class SubtitleFont:
    family: str
    path: Path

    def __post_init__(self) -> None:
        if not self.family.strip() or any(
            character in ",:;=[]'\\" or ord(character) < 32 for character in self.family
        ):
            raise ValueError("Subtitle font name must be a plain font family")
        if self.path.suffix.lower() not in {".ttf", ".ttc", ".otf"}:
            raise ValueError("Subtitle font must be a TTF, TTC or OTF file")

    def to_record(self) -> dict[str, str]:
        return {"family": self.family, "path": str(self.path.absolute())}


def resolve_subtitle_font(
    environ: Mapping[str, str] | None = None,
    *,
    platform: str | None = None,
) -> SubtitleFont:
    """Choose an installed CJK font, or accept an explicit path/family pair."""
    values = os.environ if environ is None else environ
    font_path = values.get("MINICUT_SUBTITLE_FONT_PATH", "").strip()
    family = values.get("MINICUT_SUBTITLE_FONT_NAME", "").strip()
    if bool(font_path) != bool(family):
        raise UserInputError(
            "Set both MINICUT_SUBTITLE_FONT_PATH and MINICUT_SUBTITLE_FONT_NAME"
        )
    if font_path:
        try:
            candidates = (SubtitleFont(family, Path(font_path).expanduser()),)
        except ValueError as error:
            raise UserInputError(str(error)) from error
    else:
        selected_platform = sys.platform if platform is None else platform
        if selected_platform == "darwin":
            candidates = (
                SubtitleFont(
                    "Arial Unicode MS", Path("/Library/Fonts/Arial Unicode.ttf")
                ),
                SubtitleFont(
                    "Heiti SC", Path("/System/Library/Fonts/STHeiti Light.ttc")
                ),
            )
        elif selected_platform == "win32":
            font_directory = Path(values.get("WINDIR", "C:/Windows")) / "Fonts"
            candidates = (SubtitleFont("Microsoft YaHei", font_directory / "msyh.ttc"),)
        else:
            candidates = (
                SubtitleFont(
                    "Noto Sans CJK SC",
                    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
                ),
                SubtitleFont(
                    "Noto Sans CJK SC",
                    Path("/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc"),
                ),
            )
    for candidate in candidates:
        if candidate.path.is_file() and os.access(candidate.path, os.R_OK):
            return candidate
    raise UserInputError(
        "Burned subtitles require a readable CJK font. Set "
        "MINICUT_SUBTITLE_FONT_PATH to an installed TTF/TTC/OTF and "
        "MINICUT_SUBTITLE_FONT_NAME to its font family (for example Noto Sans CJK SC)."
    )
