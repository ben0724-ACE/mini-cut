"""Explicit local fonts for burned subtitles; never download or bundle fonts."""

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from PIL import ImageFont

from minicut.errors import UserInputError


@dataclass(frozen=True, slots=True)
class SubtitleFont:
    family: str
    path: Path
    index: int = 0

    def __post_init__(self) -> None:
        if not self.family.strip() or any(
            character in ",:;=[]'\\" or ord(character) < 32 for character in self.family
        ):
            raise ValueError("Subtitle font name must be a plain font family")
        if self.path.suffix.lower() not in {".ttf", ".ttc", ".otf"}:
            raise ValueError("Subtitle font must be a TTF, TTC or OTF file")

    def to_record(self) -> dict[str, str]:
        return {"family": self.family, "path": str(self.path.absolute())}


def available_subtitle_fonts() -> dict[str, tuple[str, SubtitleFont]]:
    """Use the same installed fonts as covers, with their real family names."""
    # Import locally because cover design also uses the default font resolver.
    from minicut.cover_design import cover_fonts

    fonts: dict[str, tuple[str, SubtitleFont]] = {}
    for key, (name, path) in cover_fonts().items():
        # Heiti's medium face is selected by the shared bold switch.
        if key == "heiti_medium":
            continue
        if not os.access(path, os.R_OK):
            continue
        try:
            index = 1 if key == "heiti" else 6 if key == "songti" else 0
            face = ImageFont.truetype(str(path), 32, index=index)
            family = face.getname()[0]
            if key == "configured":
                configured = resolve_subtitle_font()
                family = configured.family
            if not family:
                continue
            fonts[key] = (name, SubtitleFont(family, path, index))
        except (OSError, ValueError, UserInputError):
            continue
    return fonts


def resolve_selected_subtitle_font(font_id: str) -> SubtitleFont:
    entry = available_subtitle_fonts().get(font_id)
    if entry is None:
        raise UserInputError("字幕字体不可用，请选择本机可用的字体")
    return entry[1]


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
