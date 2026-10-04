"""Local cover layouts, immutable versions and deterministic image composition."""

import io
import json
import os
import sqlite3
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal

from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field

from minicut.errors import UserInputError
from minicut.ffmpeg_paths import ffmpeg_file
from minicut.highlight_service import source_segments
from minicut.output_plan import OutputPlan, validate_output_id
from minicut.output_repository import OutputCollectionRepository
from minicut.project import ProjectRepository
from minicut.renderer import FfmpegRenderer
from minicut.subtitle_font import resolve_subtitle_font
from minicut.transcription_task import CancellationToken

SIZES = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
    "3:4": (1080, 1440),
}


class CoverBox(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    x: float = Field(default=0.08, ge=-1, le=1)
    y: float = Field(default=0.14, ge=-1, le=1)
    width: float = Field(default=0.84, ge=0.05, le=2)
    height: float = Field(default=0.46, ge=0.05, le=2)


class CoverStyle(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    mode: Literal["first_frame", "design"] = "first_frame"
    aspect_ratio: Literal["9:16", "16:9", "1:1", "3:4"] = "9:16"
    background_color: str = Field(default="#172033", pattern=r"^#[0-9a-fA-F]{6}$")
    background_image: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    background_scale: float = Field(default=1, ge=1, le=4)
    background_x: float = Field(default=0.5, ge=0, le=1)
    background_y: float = Field(default=0.5, ge=0, le=1)
    frame: CoverBox = Field(default_factory=CoverBox)
    frame_fit: Literal["contain", "crop"] = "contain"
    title_box: CoverBox = Field(default_factory=lambda: CoverBox(y=0.66, height=0.25))
    font_id: str | None = Field(default=None, pattern=r"^[a-z0-9_-]+$")
    font_size: int = Field(default=88, ge=16, le=300)
    bold: bool = True
    text_color: str = Field(default="#ffffff", pattern=r"^#[0-9a-fA-F]{6}$")
    stroke_color: str = Field(default="#000000", pattern=r"^#[0-9a-fA-F]{6}$")
    stroke_width: int = Field(default=0, ge=0, le=12)
    align: Literal["left", "center", "right"] = "center"


class CoverDesign(CoverStyle):
    frame_ms: int | None = Field(default=None, ge=0, strict=True)
    title: str = Field(default="", max_length=500)
    template_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]+$")
    template_name: str | None = Field(default=None, max_length=80)


def cover_fonts() -> dict[str, tuple[str, Path]]:
    candidates = {
        "heiti": ("黑体（中文）", Path("/System/Library/Fonts/STHeiti Light.ttc")),
        "heiti_medium": (
            "黑体中等（中文）",
            Path("/System/Library/Fonts/STHeiti Medium.ttc"),
        ),
        "songti": (
            "宋体（中文）",
            Path("/System/Library/Fonts/Supplemental/Songti.ttc"),
        ),
        "hiragino": (
            "冬青黑体（中文）",
            Path("/System/Library/Fonts/Hiragino Sans GB.ttc"),
        ),
        "noto": (
            "Noto Sans CJK",
            Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        ),
        "noto_alt": (
            "Noto Sans CJK",
            Path("/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc"),
        ),
        "yahei": (
            "微软雅黑",
            Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/msyh.ttc",
        ),
    }
    try:
        configured = resolve_subtitle_font()
        candidates["configured"] = (configured.family, configured.path)
    except UserInputError:
        pass
    return {key: value for key, value in candidates.items() if value[1].is_file()}


def design_directory(project: Path, collection: str, output: str) -> Path:
    validate_output_id(collection)
    validate_output_id(output)
    return project / ".minicut/covers" / collection / output


class CoverStore:
    def __init__(self, project: Path, collection: str, output: str) -> None:
        self.directory = design_directory(project, collection, output)

    def read(self, version: int | None = None) -> tuple[int, CoverDesign] | None:
        path = self.directory / "designs.sqlite3"
        if not path.exists():
            return None
        with sqlite3.connect(path) as db:
            row = db.execute(
                "SELECT version, design FROM designs "
                + (
                    "ORDER BY version DESC LIMIT 1"
                    if version is None
                    else "WHERE version=?"
                ),
                () if version is None else (version,),
            ).fetchone()
        return (row[0], CoverDesign.model_validate_json(row[1])) if row else None

    def save(self, design: CoverDesign, base_version: int) -> int:
        self.directory.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.directory / "designs.sqlite3") as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS designs (version INTEGER PRIMARY KEY, design TEXT NOT NULL)"
            )
            db.execute("BEGIN IMMEDIATE")
            current = db.execute(
                "SELECT COALESCE(MAX(version),0) FROM designs"
            ).fetchone()[0]
            if current != base_version:
                raise UserInputError("封面已在其他页面修改，请重新载入后保存")
            version = current + 1
            db.execute(
                "INSERT INTO designs VALUES (?,?)", (version, design.model_dump_json())
            )
        return version


def cover_context(
    project: Path, collection: str, output: str, revision: int
) -> tuple[OutputPlan, Path, list[tuple[int, int]]]:
    repository = OutputCollectionRepository(project, collection)
    try:
        asset_id = json.loads(repository.path.read_text(encoding="utf-8"))["asset_id"]
        segments = source_segments(project, asset_id, collection)
        plan = next(p for p in repository.read(segments).plans if p.output_id == output)
        if plan.revision != revision:
            raise UserInputError("作品版本已变更，请刷新后设计封面")
        lookup = {s.segment_id: s for s in segments}
        ranges = [
            (
                i.source_start_ms
                if i.source_start_ms is not None
                else lookup[i.segment_id].start_ms,
                i.source_end_ms
                if i.source_end_ms is not None
                else lookup[i.segment_id].end_ms,
            )
            for i in plan.items
            if not i.deleted
        ]
        asset = next(
            a
            for a in ProjectRepository(project).read().assets
            if a.asset_id == asset_id
        )
        return plan, Path(asset.source_path), ranges
    except (OSError, ValueError, KeyError, StopIteration) as error:
        raise UserInputError("找不到作品或源视频") from error


def validate_design(
    project: Path, collection: str, output: str, revision: int, design: CoverDesign
) -> tuple[Path, int]:
    _, source, ranges = cover_context(project, collection, output, revision)
    frame_ms = ranges[0][0] if design.frame_ms is None else design.frame_ms
    if design.mode == "design":
        if not any(start <= frame_ms < end for start, end in ranges):
            raise UserInputError("所选帧已不在作品保留片段内，请重新选择")
        if not cover_fonts() or (
            design.font_id and design.font_id not in cover_fonts()
        ):
            raise UserInputError("封面字体不可用，请选择本机可用的中文字体")
        if (
            design.background_image
            and not (
                design_directory(project, collection, output)
                / f"{design.background_image}.png"
            ).is_file()
        ):
            raise UserInputError("背景图片不存在，请重新上传")
    return source, frame_ms


def extract_frame(
    source: Path, destination: Path, frame_ms: int, token: CancellationToken
) -> None:
    FfmpegRenderer().render_to_path(
        (
            "ffmpeg",
            "-nostdin",
            "-y",
            "-ss",
            f"{frame_ms / 1000:.3f}",
            "-i",
            ffmpeg_file(source),
            "-map",
            "0:v:0",
            "-frames:v",
            "1",
            "-update",
            "1",
            "-vf",
            "scale='min(1920,iw)':-1",
            ffmpeg_file(destination),
        ),
        destination,
        timeout_seconds=120,
        cancellation=token,
    )


def cached_frame(
    project: Path,
    collection: str,
    output: str,
    source: Path,
    frame_ms: int,
    token: CancellationToken,
) -> Path:
    directory = design_directory(project, collection, output)
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"frame-{frame_ms}.png"
    if not destination.is_file():
        with NamedTemporaryFile(dir=directory, suffix=".png", delete=False) as stream:
            temporary = Path(stream.name)
        try:
            extract_frame(source, temporary, frame_ms, token)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
    return destination


def normalize_background(data: bytes) -> bytes:
    try:
        with Image.open(io.BytesIO(data)) as original:
            if (
                original.format not in {"JPEG", "PNG", "WEBP"}
                or original.width * original.height > 36_000_000
            ):
                raise UserInputError("请上传不超过 3600 万像素的 JPG、PNG 或 WebP 图片")
            image = ImageOps.exif_transpose(original).convert("RGBA")
            image.thumbnail((3840, 3840))
            stream = io.BytesIO()
            image.save(stream, format="PNG")
            return stream.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise UserInputError(
            "无法读取背景图片，请选择有效的 JPG、PNG 或 WebP"
        ) from error


def compose_cover(
    design: CoverDesign,
    frame_path: Path,
    background: Path | None,
    image_format: str = "png",
) -> tuple[bytes, list[str]]:
    width, height = SIZES[design.aspect_ratio]
    canvas = Image.new("RGB", (width, height), design.background_color)
    warnings: list[str] = []
    if background:
        with Image.open(background) as original:
            image = original.convert("RGBA")
        scale = (
            max(width / image.width, height / image.height) * design.background_scale
        )
        crop_width, crop_height = width / scale, height / scale
        left = (image.width - crop_width) * design.background_x
        top = (image.height - crop_height) * design.background_y
        image = image.resize(
            (width, height),
            Image.Resampling.LANCZOS,
            box=(left, top, left + crop_width, top + crop_height),
        )
        canvas.paste(image, (0, 0), image)

    def bounds(box: CoverBox) -> tuple[int, int, int, int]:
        x, y, w, h = (
            round(box.x * width),
            round(box.y * height),
            round(box.width * width),
            round(box.height * height),
        )
        if x < 0 or y < 0 or x + w > width or y + h > height:
            warnings.append("元素超出画布，导出时超出的部分会被裁掉")
        return x, y, w, h

    x, y, w, h = bounds(design.frame)
    with Image.open(frame_path) as original:
        frame = original.convert("RGB")
    frame = (
        ImageOps.fit(frame, (w, h))
        if design.frame_fit == "crop"
        else ImageOps.contain(frame, (w, h))
    )
    canvas.paste(frame, (x + (w - frame.width) // 2, y + (h - frame.height) // 2))
    x, y, w, h = bounds(design.title_box)
    fonts = cover_fonts()
    if not fonts:
        raise UserInputError(
            "未找到可用中文字体，请配置 MINICUT_SUBTITLE_FONT_PATH 和 MINICUT_SUBTITLE_FONT_NAME"
        )
    font_path = fonts[design.font_id or next(iter(fonts))][1]
    font = ImageFont.truetype(str(font_path), design.font_size)
    stroke = design.stroke_width + (
        max(1, design.font_size // 40) if design.bold else 0
    )
    layer = Image.new("RGBA", (w, h))
    draw = ImageDraw.Draw(layer)
    lines: list[str] = []
    for paragraph in design.title.split("\n"):
        line = ""
        for character in paragraph:
            if line and draw.textlength(line + character, font=font) > w - stroke * 2:
                lines.append(line)
                line = ""
            line += character
        lines.append(line)
    line_height = round(design.font_size * 1.3)
    if len(lines) * line_height + stroke * 2 > h:
        warnings.append("标题超出文本框，请减小字号、扩大文本框或精简标题")
    for index, line in enumerate(lines):
        length = draw.textlength(line, font=font)
        offset = (
            stroke
            if design.align == "left"
            else w - length - stroke
            if design.align == "right"
            else (w - length) / 2
        )
        draw.text(
            (offset, index * line_height + stroke),
            line,
            font=font,
            fill=design.text_color,
            anchor="lt",
            stroke_width=stroke,
            stroke_fill=design.stroke_color
            if design.stroke_width
            else design.text_color,
        )
    canvas.paste(layer, (x, y), layer)
    stream = io.BytesIO()
    canvas.save(stream, format="JPEG" if image_format == "jpg" else "PNG", quality=95)
    return stream.getvalue(), list(dict.fromkeys(warnings))


def render_cover(
    project: Path,
    collection: str,
    output: str,
    revision: int,
    design: CoverDesign,
    image_format: str = "png",
    token: CancellationToken | None = None,
) -> tuple[bytes, list[str]]:
    if design.mode != "design":
        raise UserInputError("成片第一帧需要先导出视频，请切换为自定义封面进行预览")
    source, frame_ms = validate_design(project, collection, output, revision, design)
    token = token or CancellationToken()
    token.raise_if_cancelled()
    frame = cached_frame(project, collection, output, source, frame_ms, token)
    background = (
        design_directory(project, collection, output) / f"{design.background_image}.png"
        if design.background_image
        else None
    )
    return compose_cover(design, frame, background, image_format)
