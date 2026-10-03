"""Verify saved typography, effect pixels, and audio through the real renderer."""

import json
import shutil
import subprocess
from array import array
from dataclasses import replace
from math import sqrt
from pathlib import Path
from typing import cast

import pytest
from PIL import Image, ImageChops

from minicut.media import MediaAsset
from minicut.output_plan import (
    HighlightCandidate,
    OutputCollection,
    OutputItem,
    OutputPlan,
    OutputRole,
)
from minicut.output_render import OutputRenderRequest, RenderOutputUseCase
from minicut.output_repository import OutputCollectionRepository
from minicut.probe import probe_media
from minicut.project import ProjectManifest, ProjectRepository
from minicut.render_command import SubtitleMode, VideoOutputMetadata
from minicut.semantic_segment import SemanticSegment
from minicut.subtitle_font import available_subtitle_fonts
from minicut.subtitle_layout import SubtitleGeometry
from minicut.subtitle_style import SubtitleStyle
from minicut.transcript import Transcript, TranscriptSource, Word

pytestmark = pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg required"
)


def frame(path: Path, width: int, height: int) -> Image.Image:
    raw = subprocess.check_output(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            "0.8",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-pix_fmt",
            "rgb24",
            "-f",
            "rawvideo",
            "-",
        ],
        timeout=30,
    )
    return Image.frombytes("RGB", (width, height), raw)


def audio(path: Path) -> bytes:
    return subprocess.check_output(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "8000",
            "-f",
            "s16le",
            "-",
        ],
        timeout=30,
    )


def assert_same_glyphs(before: Image.Image, after: Image.Image) -> None:
    # H.264 can adjust antialiasing pixels when another region changes complexity.
    masks = [
        image.convert("L").point([0] * 201 + [255] * 55) for image in (before, after)
    ]
    assert masks[0].getbbox() == masks[1].getbbox()
    difference = ImageChops.difference(*masks).histogram()[255]
    assert difference <= max(3, masks[0].histogram()[255] * 0.01)


def test_saved_fonts_sizes_and_effects_reach_real_video(tmp_path: Path) -> None:
    fonts = available_subtitle_fonts()
    ids = [
        key
        for key in ("heiti", "songti", "noto", "yahei", "configured")
        if key in fonts
    ]
    if not ids:
        pytest.skip("Installed CJK font required")
    font_id = ids[0]
    source = tmp_path / "source.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=gray:s=320x180:r=5:d=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=2",
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
    probed = probe_media(source)
    asset = MediaAsset("a", str(source), probed.duration_ms, probed.streams, "fixture")
    ProjectRepository(tmp_path).create(ProjectManifest("p", (asset,)))
    segment = SemanticSegment("s", "Hello subtitle", 0, 2000, ("u",), ("w",))
    transcript = Transcript(
        "t",
        TranscriptSource("a", "fixture", "fixture"),
        "en",
        (Word("w", segment.text, 0, 2000),),
    )
    style = SubtitleStyle(
        source_font_id=font_id,
        translation_font_id=font_id,
        source_size=72,
        translation_size=54,
        bold=False,
        stroke_width=0,
        background_enabled=True,
    )
    plan = OutputPlan(
        "v",
        "c",
        "T",
        (
            OutputItem(
                "i",
                "s",
                OutputRole.BODY,
                translation_text="字幕优化测试",
                translation_language="zh",
            ),
        ),
        subtitle_style=style,
    )
    collection = OutputCollection(
        "c",
        "a",
        (HighlightCandidate("c", "T", "R", ("s",)),),
        (plan,),
    )
    repository = OutputCollectionRepository(tmp_path, "c")
    repository.write(collection, (segment,))
    use_case = RenderOutputUseCase()

    def render(
        saved_style: SubtitleStyle, short: int, label: str
    ) -> tuple[Image.Image, Path]:
        saved = replace(plan, subtitle_style=saved_style)
        repository.write(replace(collection, plans=(saved,)), (segment,))
        result = use_case.execute(
            OutputRenderRequest(
                tmp_path,
                "c",
                "v",
                (segment,),
                transcript,
                subtitle_mode=SubtitleMode.BURNED,
                video_metadata=VideoOutputMetadata(
                    short, short * 16 // 9, "5", fit="crop"
                ),
                export_id=label,
            )
        )
        record = json.loads(result.record_path.read_text())
        assert (
            record["plan"]["subtitle_style"]["source_font_id"]
            == saved_style.source_font_id
        )
        assert (
            record["subtitle_font"]["family"]
            == fonts[saved_style.source_font_id or font_id][1].family
        )
        assert (
            record["subtitle_translation_font"]["family"]
            == fonts[saved_style.translation_font_id or font_id][1].family
        )
        assert abs(probe_media(result.output_path).duration_ms - 2000) <= 200
        return frame(result.output_path, short, short * 16 // 9), result.output_path

    images: list[Image.Image] = []
    first_path: Path | None = None
    for short in (720, 1080):
        image, path = render(style, short, f"size-{short}")
        images.append(image)
        first_path = first_path or path
        layout = SubtitleGeometry.for_output(
            short, short * 16 // 9, plan, fonts[font_id][1]
        )
        top = (
            layout.height
            - layout.bottom
            - 2 * layout.row_height(layout.translation_large)
        )
        # Empty padding inside a black 50% box over gray is approximately 64.
        assert (
            45
            <= cast(
                tuple[int, int, int],
                image.getpixel((short // 2, top - layout.effect_padding + 2)),
            )[0]
            <= 85
        )
        white = image.convert("L").point([0] * 201 + [255] * 55)
        bounds = white.getbbox()
        assert bounds is not None
        assert bounds[0] > layout.side and bounds[2] < short - layout.side
    boxes = [
        image.convert("L").point([0] * 201 + [255] * 55).getbbox() for image in images
    ]
    assert boxes[0] is not None and boxes[1] is not None
    assert (boxes[0][2] - boxes[0][0]) / 720 == pytest.approx(
        (boxes[1][2] - boxes[1][0]) / 1080, abs=0.015
    )
    assert first_path is not None
    # The timeline encoder may re-encode AAC; compare decoded speech samples.
    source_samples = array("h", audio(source))
    rendered_samples = array("h", audio(first_path))
    end = min(len(source_samples), len(rendered_samples)) - 500
    pairs = list(zip(source_samples[500:end], rendered_samples[500:end], strict=True))
    correlation = sum(a * b for a, b in pairs) / sqrt(
        sum(a * a for a, _ in pairs) * sum(b * b for _, b in pairs)
    )
    assert correlation > 0.99

    transparent, _ = render(replace(style, background_opacity=0), 720, "transparent")
    opaque, _ = render(replace(style, background_opacity=100), 720, "opaque")
    assert ImageChops.difference(transparent, opaque).getbbox() is not None
    layout = SubtitleGeometry.for_output(720, 1280, plan, fonts[font_id][1])
    top = 1280 - layout.bottom - 2 * layout.row_height(layout.translation_large)
    point = (360, top - layout.effect_padding + 2)
    assert 110 <= cast(tuple[int, int, int], transparent.getpixel(point))[0] <= 140
    assert cast(tuple[int, int, int], opaque.getpixel(point))[0] < 15

    effects, _ = render(
        replace(
            style,
            text_color="#ffff00",
            stroke_color="#ff0000",
            stroke_width=6,
            shadow_color="#0000ff",
            shadow_width=8,
            bold=True,
            background_enabled=False,
        ),
        720,
        "effects",
    )
    raw = effects.tobytes()
    pixels = list(zip(raw[::3], raw[1::3], raw[2::3], strict=True))
    assert sum(r > 180 and g > 180 and b < 100 for r, g, b in pixels) > 100
    assert sum(r > 170 and g < 100 and b < 100 for r, g, b in pixels) > 100
    assert sum(b > r + 30 and b > g + 30 for r, g, b in pixels) > 50
    if len(ids) > 1:
        different, _ = render(
            replace(style, translation_font_id=ids[1]), 720, "second-font"
        )
        # Changing one font leaves the other language's glyphs and position unchanged.
        split_y = (
            1280
            - layout.bottom
            - 2 * layout.row_height(layout.translation_large)
            - layout.gap // 2
        )
        assert_same_glyphs(
            images[0].crop((0, 0, 720, split_y)),
            different.crop((0, 0, 720, split_y)),
        )
        assert (
            ImageChops.difference(
                images[0].crop((0, split_y, 720, 1280)),
                different.crop((0, split_y, 720, 1280)),
            ).getbbox()
            is not None
        )
        changed_source, _ = render(
            replace(style, source_font_id=ids[1]), 720, "source-font"
        )
        assert_same_glyphs(
            images[0].crop((0, split_y, 720, 1280)),
            changed_source.crop((0, split_y, 720, 1280)),
        )
        assert (
            ImageChops.difference(
                images[0].crop((0, 0, 720, split_y)),
                changed_source.crop((0, 0, 720, split_y)),
            ).getbbox()
            is not None
        )
