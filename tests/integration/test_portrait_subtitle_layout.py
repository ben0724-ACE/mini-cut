"""Measure the actual libass pixels as bilingual line counts change."""

import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from minicut.errors import UserInputError
from minicut.output_plan import OutputItem, OutputPlan, OutputRole
from minicut.render_command import (
    RenderCommandBuilder,
    SubtitleMode,
    VideoOutputMetadata,
)
from minicut.subtitle_ass import render_translated_ass
from minicut.subtitle_font import resolve_subtitle_font
from minicut.subtitle_layout import SubtitleGeometry
from minicut.subtitle_pages import SubtitlePage


@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg required"
)
@pytest.mark.parametrize("resolution", [720, 1080])
@pytest.mark.parametrize("order", ["source_first", "translation_first"])
def test_burned_first_rows_do_not_move_and_keep_original_audio(
    tmp_path: Path, resolution: int, order: str
) -> None:
    try:
        font = resolve_subtitle_font()
    except UserInputError as error:
        pytest.skip(str(error))
    width, height = resolution, resolution * 16 // 9
    plan = OutputPlan(
        "v", "c", "T", (OutputItem("i", "s", OutputRole.BODY),), subtitle_order=order
    )
    geometry = SubtitleGeometry.for_output(width, height, plan, font)
    pages = tuple(
        SubtitlePage(
            i * 1500,
            (i + 1) * 1500,
            "Same first English row"
            + ("\nSecond English row" if source_rows == 2 else ""),
            "第一行中文" + ("\n第二行中文" if translated_rows == 2 else ""),
            "zh",
        )
        for i, (source_rows, translated_rows) in enumerate(
            ((1, 1), (1, 2), (2, 1), (2, 2))
        )
    )
    source, subtitle, burned = (
        tmp_path / "source.mp4",
        tmp_path / "layout.ass",
        tmp_path / "burned.mp4",
    )
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=black:s={width}x{height}:r=10:d=6",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=6",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(source),
        ],
        capture_output=True,
        check=True,
        timeout=30,
    )
    subtitle.write_text(render_translated_ass(pages, width, height, font, plan))
    command = RenderCommandBuilder().build_subtitle_output(
        str(source),
        str(subtitle),
        str(burned),
        SubtitleMode.BURNED,
        subtitle_font=font,
        video_metadata=VideoOutputMetadata(width, height),
        styled_subtitles=True,
    )
    subprocess.run(command, capture_output=True, check=True, timeout=30)
    source_step, translated_step = (
        geometry.row_height(geometry.source_small),
        geometry.row_height(geometry.translation_large),
    )
    if order == "translation_first":
        source_y = height - geometry.bottom - source_step * 2
        translated_y = source_y - geometry.gap - translated_step * 2
    else:
        translated_y = height - geometry.bottom - translated_step * 2
        source_y = translated_y - geometry.gap - source_step * 2
    first_rows: list[tuple[tuple[int, int, int, int] | None, ...]] = []
    for second in ("0.5", "2", "3.5", "5"):
        pixels = subprocess.check_output(
            [
                "ffmpeg",
                "-v",
                "error",
                "-ss",
                second,
                "-i",
                str(burned),
                "-frames:v",
                "1",
                "-pix_fmt",
                "gray",
                "-f",
                "rawvideo",
                "-",
            ],
            timeout=10,
        )
        image = Image.frombytes("L", (width, height), pixels).point(
            [0] * 161 + [255] * 95
        )
        box = image.getbbox()
        assert (
            box is not None
            and box[0] >= geometry.side
            and box[2] <= width - geometry.side
        )
        assert (
            box[1] >= min(source_y, translated_y) and box[3] <= height - geometry.bottom
        )
        rows = tuple(
            image.crop((0, top, width, top + step)).getbbox()
            for top, step in ((source_y, source_step), (translated_y, translated_step))
        )
        assert all(row is not None for row in rows)
        first_rows.append(rows)
    assert all(rows == first_rows[0] for rows in first_rows)

    def audio(path: Path) -> bytes:
        return subprocess.check_output(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(path),
                "-map",
                "0:a:0",
                "-f",
                "s16le",
                "-",
            ],
            timeout=10,
        )

    assert audio(source) == audio(burned)
