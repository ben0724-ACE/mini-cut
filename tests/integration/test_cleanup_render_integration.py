"""Many non-frame-aligned cuts must not accumulate AV/subtitle drift."""

import array
import json
import subprocess
from pathlib import Path

import pytest

from minicut.media import MediaAsset
from minicut.output_render import OutputRenderRequest, RenderOutputUseCase
from minicut.output_repository import OutputCollectionRepository
from minicut.probe import probe_media
from minicut.project import ProjectManifest, ProjectRepository
from minicut.render_command import SubtitleMode, VideoOutputMetadata
from minicut.sentence_boundaries import sentence_segments
from minicut.speech_cleanup import Deletion, build_cleanup
from minicut.transcript import Transcript, TranscriptSource, Word


@pytest.mark.parametrize("has_audio", [True, False])
@pytest.mark.parametrize("subtitle_mode", [SubtitleMode.SOFT, SubtitleMode.BURNED])
def test_many_cleanup_cuts_keep_one_clock_and_tail_audio(
    tmp_path: Path, has_audio: bool, subtitle_mode: SubtitleMode
) -> None:
    source = tmp_path / "many-cuts.mp4"
    command = [
        "ffmpeg",
        "-v",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=red:size=160x120:rate=25:duration=40.5",
    ]
    if has_audio:
        command += [
            "-f",
            "lavfi",
            "-i",
            "aevalsrc='if(lt(t,20),0.1*sin(2*PI*220*t),0.1*sin(2*PI*880*t))':sample_rate=48000:duration=40.5",
            "-c:a",
            "aac",
        ]
    command += [
        "-vf",
        "drawbox=color=blue:t=fill:enable='gte(t,20)'",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(source),
    ]
    subprocess.run(command, check=True, capture_output=True)
    probe = probe_media(source)
    asset = MediaAsset("a", str(source), probe.duration_ms, probe.streams, "fixture")
    ProjectRepository(tmp_path).create(ProjectManifest("test", (asset,)))
    transcript = Transcript(
        "t",
        TranscriptSource("a", "test", "test"),
        "zh",
        tuple(
            Word(f"w{i}", f"原文{i}。", i * 250 + 10, i * 250 + 80) for i in range(162)
        ),
    )
    collection, _ = build_cleanup(
        transcript,
        40500,
        "清理版",
        "cleanup",
        [Deletion(i * 250 + 173, (i + 1) * 250, "长停顿") for i in range(162)],
    )
    segments = sentence_segments(transcript)
    OutputCollectionRepository(tmp_path, "cleanup").write(collection, segments)
    result = RenderOutputUseCase().execute(
        OutputRenderRequest(
            tmp_path,
            "cleanup",
            "cleanup",
            segments,
            transcript,
            timeout_seconds=60,
            subtitle_mode=subtitle_mode,
            video_metadata=VideoOutputMetadata(160, 120, "25"),
        )
    )
    assert result.timeline.estimated_duration_ms == 162 * 173
    assert abs(probe_media(result.output_path).duration_ms - 162 * 173) <= 40
    assert "原文 161" in result.subtitle_path.read_text()
    # A tail frame is still from the source's second half, after all deletions.
    pixels = subprocess.check_output(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            "27.5",
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
    assert sum(pixels[2::3]) / len(pixels[2::3]) > 150
    assert sum(pixels[0::3]) / len(pixels[0::3]) < 50
    if has_audio:
        stream = json.loads(
            subprocess.check_output(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-select_streams",
                    "a:0",
                    "-show_entries",
                    "stream=duration",
                    "-of",
                    "json",
                    str(result.output_path),
                ]
            )
        )["streams"][0]
        assert abs(float(stream["duration"]) * 1000 - 162 * 173) <= 1
        audio = subprocess.check_output(
            [
                "ffmpeg",
                "-v",
                "error",
                "-ss",
                "27.5",
                "-i",
                str(result.output_path),
                "-t",
                "0.1",
                "-vn",
                "-ar",
                "8000",
                "-ac",
                "1",
                "-f",
                "s16le",
                "-",
            ]
        )
        samples = array.array("h", audio)
        crossings = sum(
            (a < 0) != (b < 0) for a, b in zip(samples, samples[1:], strict=False)
        )
        assert 165 <= crossings <= 187  # 880 Hz at the end, after 162 cuts.
