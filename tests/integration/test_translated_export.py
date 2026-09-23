import asyncio
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from minicut.media import MediaAsset, StreamType
from minicut.output_render import OutputRenderRequest, RenderOutputUseCase
from minicut.output_repository import OutputCollectionRepository
from minicut.probe import probe_media
from minicut.project import ProjectManifest, ProjectRepository
from minicut.render_command import VideoOutputMetadata
from minicut.subtitle_translation import translate_collection
from tests.test_subtitle_translation import Translator, fixture


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required")
@pytest.mark.parametrize("mode", ["bilingual", "translated"])
def test_translated_soft_subtitle_export_keeps_audio_and_time(
    tmp_path: Path, mode: str
) -> None:
    source = tmp_path / "source.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=blue:s=160x120:r=25:d=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(source),
        ],
        check=True,
        capture_output=True,
    )
    probe = probe_media(source)
    ProjectRepository(tmp_path).create(
        ProjectManifest(
            "test",
            (MediaAsset("a", str(source), probe.duration_ms, probe.streams, "test"),),
        )
    )
    c, s, t = fixture()
    c = replace(c, plans=(replace(c.plans[0], items=(c.plans[0].items[1],)),))
    translated = asyncio.run(
        translate_collection(c, s, t, Translator(), "test", "zh", mode)
    )
    OutputCollectionRepository(tmp_path, "c").write(translated, s)
    result = RenderOutputUseCase().execute(
        OutputRenderRequest(
            tmp_path, "c", "v", s, t, video_metadata=VideoOutputMetadata(160, 120, "25")
        )
    )
    exported = probe_media(result.output_path)
    assert abs(exported.duration_ms - 2000) < 100
    assert any(stream.stream_type is StreamType.AUDIO for stream in exported.streams)
    text = result.subtitle_path.read_text()
    assert "你好" in text and ("Hello" in text) == (mode == "bilingual")
    muxed = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(result.output_path),
            "-map",
            "0:s:0",
            "-f",
            "srt",
            "-",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "你好" in muxed and ("Hello" in muxed) == (mode == "bilingual")
