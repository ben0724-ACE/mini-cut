"""Many non-frame-aligned cuts must not accumulate audio/subtitle drift."""

from __future__ import annotations

import array
import shutil
import subprocess
from pathlib import Path

import pytest

from minicut.media import MediaAsset, TimeRange
from minicut.probe import probe_media
from minicut.render_command import RenderCommandBuilder, VideoOutputMetadata
from minicut.timeline import Clip, Timeline
from minicut.timeline_validation import TimelineTrackRequirements


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required")
def test_many_cuts_keep_source_audio_on_output_clock(tmp_path: Path) -> None:
    source = tmp_path / "noise.mkv"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=64x48:rate=30:duration=16",
            "-f",
            "lavfi",
            "-i",
            "anoisesrc=color=pink:seed=7:sample_rate=48000:duration=16",
            "-c:v",
            "libx264",
            "-c:a",
            "pcm_s16le",
            str(source),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    info = probe_media(source)
    asset = MediaAsset("a", str(source), info.duration_ms, info.streams, "generated")
    clips = tuple(
        Clip(
            str(i),
            "a",
            str(i),
            TimeRange(i * 400, i * 400 + 217),
            TimeRange(i * 217, (i + 1) * 217),
        )
        for i in range(40)
    )
    destination = tmp_path / "edited.mp4"
    command = RenderCommandBuilder().build_multi_clip(
        Timeline(clips, 8680),
        (asset,),
        str(destination),
        TimelineTrackRequirements(require_audio=True, require_video=True),
        VideoOutputMetadata(64, 48, "30"),
    )
    subprocess.run(command, check=True, capture_output=True, timeout=30)

    def samples(path: Path, start: float, duration: float) -> array.array[int]:
        data = subprocess.check_output(
            [
                "ffmpeg",
                "-v",
                "error",
                "-ss",
                str(start),
                "-i",
                str(path),
                "-t",
                str(duration),
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
        result = array.array("h")
        result.frombytes(data)
        return result

    # Distinct noise avoids the ambiguous repeated peaks of a sine-wave test.
    for index in (0, 20, 39):
        reference = samples(source, index * 0.4 + 0.06, 0.1)
        actual = samples(destination, index * 0.217 + 0.04, 0.14)
        scores = [
            sum(
                a * b
                for a, b in zip(
                    reference, actual[lag : lag + len(reference)], strict=True
                )
            )
            for lag in range(len(actual) - len(reference) + 1)
        ]
        lag = max(range(len(scores)), key=scores.__getitem__)
        assert abs(lag / 8 - 20) <= 2, f"cut {index} drifted by {lag / 8 - 20} ms"
    assert abs(probe_media(destination).duration_ms - 8680) <= 34
