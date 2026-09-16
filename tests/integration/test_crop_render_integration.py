import shutil
import subprocess
from pathlib import Path

import pytest

from minicut.media import MediaAsset, StreamType
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
from minicut.render_profile import RenderProfile
from minicut.semantic_segment import SemanticSegment
from minicut.transcript import Transcript, TranscriptSource, Word


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required")
def test_free_crop_exports_only_right_blue_half_with_audio(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=red:size=320x240:rate=25:duration=2,drawbox=x=160:y=0:w=160:h=240:color=blue:t=fill",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-shortest",
            str(source),
        ],
        check=True,
        capture_output=True,
    )
    probe = probe_media(source)
    asset = MediaAsset("asset", str(source), probe.duration_ms, probe.streams, "test")
    ProjectRepository(tmp_path).create(ProjectManifest("crop", (asset,)))
    segment = SemanticSegment("s", "原话", 0, 2000, ("u",), ("w",))
    plan = OutputPlan("video", "c", "裁剪", (OutputItem("body", "s", OutputRole.BODY),))
    OutputCollectionRepository(tmp_path, "c").write(
        OutputCollection(
            "c", "asset", (HighlightCandidate("c", "裁剪", "测试", ("s",)),), (plan,)
        ),
        (segment,),
    )
    transcript = Transcript(
        "t",
        TranscriptSource("asset", "test", "test"),
        "zh",
        (Word("w", "原话", 0, 2000),),
    )
    result = RenderOutputUseCase().execute(
        OutputRenderRequest(
            tmp_path,
            "c",
            "video",
            (segment,),
            transcript,
            video_metadata=RenderProfile(
                crop_left=50, crop_top=10, crop_bottom=10
            ).metadata(320, 240),
        )
    )
    from minicut.render_profile import source_dimensions

    assert source_dimensions(result.output_path) == (160, 192)
    frame = subprocess.check_output(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            "0.5",
            "-i",
            str(result.output_path),
            "-frames:v",
            "1",
            "-pix_fmt",
            "rgb24",
            "-f",
            "rawvideo",
            "-",
        ]
    )
    assert frame[2] > 200 and frame[0] < 20
    media = probe_media(result.output_path)
    assert abs(media.duration_ms - 2000) < 80
    assert any(s.stream_type is StreamType.AUDIO for s in media.streams)
