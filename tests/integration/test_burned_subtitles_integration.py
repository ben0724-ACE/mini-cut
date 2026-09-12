import shutil
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from minicut.errors import UserInputError
from minicut.probe import probe_media
from minicut.render_command import RenderCommandBuilder, SubtitleMode
from minicut.renderer import FfmpegRenderer
from minicut.subtitle import parse_srt
from minicut.subtitle_font import resolve_subtitle_font


@unittest.skipUnless(
    shutil.which("ffmpeg") and shutil.which("ffprobe"),
    "ffmpeg and ffprobe are required",
)
class RealCjkSubtitleTest(unittest.TestCase):
    def test_mixed_cues_burn_with_real_font_and_soft_track_preserves_text(self) -> None:
        try:
            font = resolve_subtitle_font()
        except UserInputError as error:
            self.skipTest(str(error))
        filters = subprocess.run(
            ("ffmpeg", "-hide_banner", "-filters"),
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        if " subtitles " not in filters.stdout:
            self.skipTest("FFmpeg subtitles/libass filter is required")
        with TemporaryDirectory() as directory:
            root = Path(directory) / "字幕 [测试],v1:cut's"
            root.mkdir()
            source = root / "base.mp4"
            fixture = Path(__file__).parents[1] / "fixtures/subtitles/cjk-mixed.srt"
            subtitle = root / "中英.srt"
            shutil.copyfile(fixture, subtitle)
            subprocess.run(
                (
                    "ffmpeg",
                    "-v",
                    "error",
                    "-nostdin",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=black:size=640x360:rate=25:duration=4",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=440:duration=4",
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
                check=True,
                timeout=30,
            )
            builder = RenderCommandBuilder()
            burned = root / "burned.mp4"
            command = builder.build_subtitle_output(
                str(source),
                str(subtitle),
                str(burned),
                SubtitleMode.BURNED,
                subtitle_font=font,
            )
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr[-3000:])
            self.assertIn("fontselect:", result.stderr)
            self.assertNotIn("failed to find any fallback", result.stderr)
            self.assertNotIn("Error opening font", result.stderr)
            self.assertNotIn("Glyph ", result.stderr)
            self.assertNotIn("LastResort", result.stderr)

            frames: list[bytes] = []
            for timestamp in ("0.5", "1.5", "2.5", "3.5"):
                frame = subprocess.run(
                    (
                        "ffmpeg",
                        "-v",
                        "error",
                        "-ss",
                        timestamp,
                        "-i",
                        str(burned),
                        "-vf",
                        "crop=640:120:0:240",
                        "-frames:v",
                        "1",
                        "-pix_fmt",
                        "gray",
                        "-f",
                        "rawvideo",
                        "-",
                    ),
                    capture_output=True,
                    check=True,
                    timeout=10,
                ).stdout
                self.assertEqual(len(frame), 640 * 120)
                self.assertTrue(any(pixel > 100 for pixel in frame))
                frames.append(frame)
            self.assertEqual(len(set(frames)), 4)
            self.assertLessEqual(abs(probe_media(burned).duration_ms - 4000), 40)
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
                    str(burned),
                ),
                capture_output=True,
                text=True,
                check=True,
                timeout=10,
            )
            self.assertEqual(geometry.stdout.strip(), "640x360")

            soft = root / "soft.mp4"
            FfmpegRenderer().render_to_path(
                builder.build_subtitle_output(
                    str(source), str(subtitle), str(soft), SubtitleMode.SOFT
                ),
                soft,
                timeout_seconds=30,
            )
            extracted = subprocess.run(
                (
                    "ffmpeg",
                    "-v",
                    "error",
                    "-i",
                    str(soft),
                    "-map",
                    "0:s:0",
                    "-f",
                    "srt",
                    "-",
                ),
                capture_output=True,
                text=True,
                check=True,
                timeout=10,
            )
            self.assertEqual(
                parse_srt(extracted.stdout),
                parse_srt(fixture.read_text(encoding="utf-8")),
            )
            self.assertLessEqual(abs(probe_media(soft).duration_ms - 4000), 40)
