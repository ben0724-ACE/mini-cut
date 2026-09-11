import shutil
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from minicut.media import MediaAsset, StreamType, TimeRange
from minicut.probe import probe_media
from minicut.render_command import (
    AudioFade,
    RenderCommandBuilder,
    SubtitleMode,
    VideoOutputMetadata,
)
from minicut.renderer import FfmpegRenderer
from minicut.subtitle import (
    MappedWord,
    SubtitleLayoutPolicy,
    build_readable_cues,
    parse_srt,
    render_srt,
)
from minicut.timeline import Clip, Timeline
from minicut.timeline_validation import TimelineTrackRequirements


@unittest.skipUnless(
    shutil.which("ffmpeg") and shutil.which("ffprobe"),
    "ffmpeg and ffprobe are required",
)
class RealRenderPipelineTest(unittest.TestCase):
    def test_fixed_timeline_exports_decodable_av_and_round_trip_srt(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.mp4"
            output = root / "edited.mp4"
            generated = subprocess.run(
                (
                    "ffmpeg",
                    "-v",
                    "error",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc=size=320x240:rate=25:duration=2",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=440:sample_rate=48000:duration=2",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-shortest",
                    str(source),
                ),
                capture_output=True,
                check=False,
            )
            self.assertEqual(generated.returncode, 0, generated.stderr.decode())

            probed_source = probe_media(source)
            asset = MediaAsset(
                "asset-1",
                str(source),
                probed_source.duration_ms,
                probed_source.streams,
                "integration",
            )
            timeline = Timeline(
                (
                    Clip(
                        "clip:0",
                        "asset-1",
                        "segment-0",
                        TimeRange(100, 600),
                        TimeRange(0, 500),
                    ),
                    Clip(
                        "clip:1",
                        "asset-1",
                        "segment-1",
                        TimeRange(1_000, 1_500),
                        TimeRange(500, 1_000),
                    ),
                ),
                1_000,
            )
            command = RenderCommandBuilder().build_multi_clip(
                timeline,
                (asset,),
                str(output),
                TimelineTrackRequirements(require_audio=True, require_video=True),
                VideoOutputMetadata(320, 240, "25"),
                audio_fade=AudioFade(10),
            )
            FfmpegRenderer().render_to_path(
                command,
                output,
                timeout_seconds=30,
            )

            probed_output = probe_media(output)
            self.assertEqual(
                {stream.stream_type for stream in probed_output.streams},
                {StreamType.VIDEO, StreamType.AUDIO},
            )
            self.assertLessEqual(abs(probed_output.duration_ms - 1_000), 40)
            decoded = subprocess.run(
                ("ffmpeg", "-v", "error", "-i", str(output), "-f", "null", "-"),
                capture_output=True,
                check=False,
            )
            self.assertEqual(decoded.returncode, 0, decoded.stderr.decode())

            mapped_words = (
                MappedWord("w1", "第一段。", 50, 450, "clip:0"),
                MappedWord("w2", "第二段", 550, 950, "clip:1"),
            )
            cues = build_readable_cues(
                mapped_words,
                timeline.estimated_duration_ms,
                SubtitleLayoutPolicy(min_duration_ms=300),
            )
            subtitles = render_srt(cues, timeline.estimated_duration_ms)
            subtitle_path = root / "edited.srt"
            subtitle_path.write_text(subtitles, encoding="utf-8")

            self.assertEqual(parse_srt(subtitles), cues)
            self.assertLessEqual(cues[-1].end_ms, probed_output.duration_ms)

            soft_output = root / "soft.mp4"
            soft_command = RenderCommandBuilder().build_subtitle_output(
                str(output),
                str(subtitle_path),
                str(soft_output),
                SubtitleMode.SOFT,
            )
            FfmpegRenderer().render_to_path(
                soft_command,
                soft_output,
                timeout_seconds=30,
            )
            subtitle_codec = subprocess.run(
                (
                    "ffprobe",
                    "-v",
                    "error",
                    "-select_streams",
                    "s:0",
                    "-show_entries",
                    "stream=codec_name",
                    "-of",
                    "default=nw=1:nk=1",
                    str(soft_output),
                ),
                capture_output=True,
                check=False,
                text=True,
            )
            self.assertEqual(subtitle_codec.returncode, 0, subtitle_codec.stderr)
            self.assertEqual(subtitle_codec.stdout.strip(), "mov_text")
            soft_probe = probe_media(soft_output)
            geometry = subprocess.run(
                (
                    "ffprobe",
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=width,height",
                    "-of",
                    "csv=p=0:s=x",
                    str(soft_output),
                ),
                capture_output=True,
                check=False,
                text=True,
            )
            self.assertEqual(geometry.returncode, 0, geometry.stderr)
            self.assertEqual(geometry.stdout.strip(), "320x240")
            self.assertLessEqual(abs(soft_probe.duration_ms - 1_000), 40)


if __name__ == "__main__":
    unittest.main()
