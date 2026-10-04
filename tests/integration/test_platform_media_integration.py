"""Exercise media I/O with filenames valid on Windows, Linux and macOS."""

import subprocess
from pathlib import Path

import pytest
from PIL import Image

from minicut.audio_loudness import measure_loudness
from minicut.audio_quality import measure_audio_continuity
from minicut.cover_design import extract_frame
from minicut.ffmpeg_paths import ffmpeg_file
from minicut.output_export import _extract_cover  # pyright: ignore[reportPrivateUsage]
from minicut.probe import probe_media
from minicut.render_command import RenderCommandBuilder, SubtitleMode
from minicut.renderer import FfmpegRenderer
from minicut.subtitle_font import resolve_subtitle_font
from minicut.transcription_task import CancellationToken


@pytest.mark.parametrize("mode", [SubtitleMode.SOFT, SubtitleMode.BURNED])
def test_subtitles_audio_and_covers_with_literal_unicode_paths(
    tmp_path: Path, mode: SubtitleMode
) -> None:
    root = tmp_path / "中文 空格%20 [草稿];cut's"
    root.mkdir()
    source = root / "采访%20 原片.mp4"
    subprocess.run(
        (
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=black:size=320x180:rate=25:duration=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(source),
        ),
        check=True,
        capture_output=True,
        timeout=30,
    )
    subtitle = root / "字幕%20 中英.srt"
    subtitle.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\n你好 Hello\n", encoding="utf-8"
    )
    output = root / "成片%20 结果.mp4"
    builder = RenderCommandBuilder()
    command = builder.build_subtitle_output(
        str(source),
        str(subtitle),
        str(output),
        mode,
        subtitle_font=resolve_subtitle_font() if mode is SubtitleMode.BURNED else None,
    )
    FfmpegRenderer().render_to_path(command, output, timeout_seconds=30)
    assert abs(probe_media(output).duration_ms - 1000) <= 50
    metrics = measure_audio_continuity(output, audio_duration_ms=1000)
    assert metrics.peak_dbfs is not None and metrics.peak_dbfs > -30
    assert measure_loudness(output).input_lufs < 0
    if mode is SubtitleMode.SOFT:
        text = subprocess.check_output(
            (
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(output),
                "-map",
                "0:s:0",
                "-f",
                "srt",
                "-",
            ),
            timeout=10,
        ).decode("utf-8")
        assert "你好 Hello" in text
    else:
        frame = subprocess.check_output(
            (
                "ffmpeg",
                "-v",
                "error",
                "-ss",
                "0.5",
                "-i",
                str(output),
                "-frames:v",
                "1",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "gray",
                "-",
            ),
            timeout=10,
        )
        assert max(frame) > 150  # Text was actually burned into the black frame.
    token = CancellationToken()
    cover = root / "封面%20.jpg"
    _extract_cover(output, cover, token)
    with Image.open(cover) as image:
        assert image.size == (320, 180)
    preview = root / "预览%20.png"
    extract_frame(source, preview, 0, token)
    with Image.open(preview) as image:
        assert image.size == (320, 180)
    assert not list(root.glob(".*-*.mp4"))


@pytest.mark.parametrize("complex_graph", [False, True])
def test_real_ffmpeg_loads_large_filter_graph_from_file(
    tmp_path: Path, complex_graph: bool
) -> None:
    graph = "null" + " " * 18000
    if complex_graph:
        graph = "[0:v]" + graph + "[out]"
    output = tmp_path / "long-filter.mp4"
    command = (
        "ffmpeg",
        "-v",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=red:size=32x32:rate=25:duration=0.2",
        "-filter_complex" if complex_graph else "-vf",
        graph,
        *(("-map", "[out]") if complex_graph else ()),
        "-c:v",
        "libx264",
        str(output),
    )
    # Use the renderer's ordinary publication path as well as script loading.
    FfmpegRenderer().render_to_path(
        (*command[:-1], ffmpeg_file(output)), output, timeout_seconds=30
    )
    assert probe_media(output).duration_ms == 200
