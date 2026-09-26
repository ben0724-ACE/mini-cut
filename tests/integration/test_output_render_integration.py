import json
import shutil
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from minicut.media import MediaAsset
from minicut.output_export import _extract_cover
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
from minicut.render_command import VideoOutputMetadata
from minicut.semantic_segment import SemanticSegment
from minicut.subtitle import parse_srt
from minicut.transcript import Transcript, TranscriptSource, Word
from minicut.transcription_task import CancellationToken


@unittest.skipUnless(
    shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required"
)
class RealOutputRenderTest(unittest.TestCase):
    def test_blue_red_blue_hook_and_second_work_export_with_repeated_subtitles(
        self,
    ) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "原始素材.mp4"
            subprocess.run(
                (
                    "ffmpeg",
                    "-nostdin",
                    "-v",
                    "error",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=red:size=160x120:rate=25:duration=1",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=green:size=160x120:rate=25:duration=1",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=blue:size=160x120:rate=25:duration=1",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=440:sample_rate=48000:duration=3",
                    "-filter_complex",
                    "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]",
                    "-map",
                    "[v]",
                    "-map",
                    "3:a",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    str(source),
                ),
                capture_output=True,
                check=True,
                timeout=30,
            )
            probed = probe_media(source)
            asset = MediaAsset(
                "asset",
                str(source),
                probed.duration_ms,
                probed.streams,
                "generated-test",
            )
            ProjectRepository(root).create(ProjectManifest("test", (asset,)))
            segments = tuple(
                SemanticSegment(
                    name,
                    text,
                    index * 1000,
                    index * 1000 + 800,
                    ("u-" + name,),
                    ("w-" + name,),
                )
                for index, name, text in ((0, "a", "背景。"), (2, "c", "结论。"))
            )
            transcript = Transcript(
                "t",
                TranscriptSource("asset", "fixture", "fixture"),
                "zh",
                tuple(
                    Word(
                        segment.word_ids[0],
                        segment.text,
                        segment.start_ms,
                        segment.end_ms,
                    )
                    for segment in segments
                ),
            )
            plan = OutputPlan(
                "video-1",
                "candidate",
                "结论先行",
                (
                    OutputItem("hook-c", "c", OutputRole.HOOK),
                    OutputItem("body-a", "a", OutputRole.BODY),
                    OutputItem("body-c", "c", OutputRole.BODY),
                ),
            )
            from dataclasses import replace

            plan = replace(plan, hook_transition_ms=150)
            second_plan = OutputPlan("video-2", "candidate", "原始节选", plan.items[1:])
            collection = OutputCollection(
                "selected",
                "asset",
                (HighlightCandidate("candidate", "title", "reason", ("a", "c")),),
                (plan, second_plan),
            )
            OutputCollectionRepository(root, "selected").write(collection, segments)
            use_case = RenderOutputUseCase()
            result = use_case.execute(
                OutputRenderRequest(
                    root,
                    "selected",
                    "video-1",
                    segments,
                    transcript,
                    video_metadata=VideoOutputMetadata(160, 120, "25"),
                )
            )
            for timestamp, channel, low, high in (
                ("0.4", 2, 150, 256),
                ("0.72", 2, 100, 160),
                ("0.8", 0, -1, 10),
                ("0.88", 0, 100, 160),
                ("1.2", 0, 150, 256),
                ("2.0", 2, 150, 256),
            ):
                frame = subprocess.run(
                    (
                        "ffmpeg",
                        "-v",
                        "error",
                        "-ss",
                        timestamp,
                        "-i",
                        str(result.output_path),
                        "-frames:v",
                        "1",
                        "-pix_fmt",
                        "rgb24",
                        "-f",
                        "rawvideo",
                        "-",
                    ),
                    capture_output=True,
                    check=True,
                    timeout=10,
                ).stdout
                self.assertEqual(len(frame), 160 * 120 * 3)
                pixel = frame[(60 * 160 + 80) * 3 : (60 * 160 + 80) * 3 + 3]
                self.assertGreater(pixel[channel], low)
                self.assertLess(pixel[channel], high)
                if high == 256:
                    self.assertEqual(pixel.index(max(pixel)), channel)
            import array

            levels: list[float] = []
            for timestamp in ("0.4", "0.77", "0.82", "1.2", "2.0"):
                raw = subprocess.check_output(
                    [
                        "ffmpeg",
                        "-v",
                        "error",
                        "-ss",
                        timestamp,
                        "-i",
                        str(result.output_path),
                        "-t",
                        "0.02",
                        "-vn",
                        "-ac",
                        "1",
                        "-f",
                        "s16le",
                        "-",
                    ]
                )
                samples = array.array("h", raw)
                levels.append(sum(abs(value) for value in samples) / len(samples))
            self.assertLess(levels[1], levels[0] * 0.3)
            self.assertLess(levels[2], levels[0] * 0.3)
            self.assertGreater(levels[3], levels[0] * 0.8)
            self.assertGreater(levels[4], levels[0] * 0.8)
            extracted = subprocess.run(
                (
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
                ),
                capture_output=True,
                text=True,
                check=True,
                timeout=10,
            )
            cues = parse_srt(extracted.stdout)
            self.assertEqual([cue.text for cue in cues], ["结论。", "背景。", "结论。"])
            self.assertEqual([cue.start_ms for cue in cues], [0, 800, 1600])
            self.assertLessEqual(
                abs(probe_media(result.output_path).duration_ms - 2400), 40
            )
            cover = result.output_path.with_name("v0001-cover.jpg")
            _extract_cover(result.output_path, cover, CancellationToken())
            self.assertTrue(cover.is_file())
            cover_frame = subprocess.run(
                (
                    "ffmpeg",
                    "-v",
                    "error",
                    "-i",
                    str(cover),
                    "-pix_fmt",
                    "rgb24",
                    "-f",
                    "rawvideo",
                    "-",
                ),
                capture_output=True,
                check=True,
                timeout=10,
            ).stdout
            self.assertEqual(len(cover_frame), 160 * 120 * 3)
            cover_pixel = cover_frame[(60 * 160 + 80) * 3 : (60 * 160 + 80) * 3 + 3]
            self.assertEqual(cover_pixel.index(max(cover_pixel)), 2)
            subprocess.run(
                (
                    "ffmpeg",
                    "-v",
                    "error",
                    "-i",
                    str(result.output_path),
                    "-f",
                    "null",
                    "-",
                ),
                capture_output=True,
                check=True,
                timeout=10,
            )
            other = use_case.execute(
                OutputRenderRequest(
                    root,
                    "selected",
                    "video-2",
                    segments,
                    transcript,
                    video_metadata=VideoOutputMetadata(160, 120, "25"),
                )
            )
            self.assertNotEqual(other.output_path, result.output_path)
            self.assertTrue(result.output_path.is_file())
            self.assertLessEqual(
                abs(probe_media(other.output_path).duration_ms - 1600), 40
            )
            record = json.loads(result.record_path.read_text(encoding="utf-8"))
            self.assertEqual(record["plan"]["output_id"], "video-1")
            self.assertEqual(record["timeline"]["clips"][0]["segment_id"], "c")
            self.assertEqual(probe_media(source).duration_ms, probed.duration_ms)

            # Continuous range includes the green middle, even though the model
            # selected only red and blue source units.
            continuous = replace(
                second_plan,
                revision=2,
                items=(
                    OutputItem(
                        "continuous",
                        "a",
                        OutputRole.BODY,
                        source_start_ms=0,
                        source_end_ms=2800,
                    ),
                ),
            )
            OutputCollectionRepository(root, "selected").write(
                replace(collection, plans=(plan, continuous)), segments
            )
            kept = use_case.execute(
                OutputRenderRequest(
                    root,
                    "selected",
                    "video-2",
                    segments,
                    transcript,
                    video_metadata=VideoOutputMetadata(160, 120, "25"),
                )
            )
            frame = subprocess.check_output(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-ss",
                    "1.5",
                    "-i",
                    str(kept.output_path),
                    "-frames:v",
                    "1",
                    "-pix_fmt",
                    "rgb24",
                    "-f",
                    "rawvideo",
                    "-",
                ]
            )
            pixel = frame[(60 * 160 + 80) * 3 : (60 * 160 + 80) * 3 + 3]
            self.assertEqual(pixel.index(max(pixel)), 1)
            self.assertLessEqual(
                abs(probe_media(kept.output_path).duration_ms - 2800), 40
            )
            self.assertTrue(
                any(
                    stream.stream_type.value == "audio"
                    for stream in probe_media(kept.output_path).streams
                )
            )

            # The effect occupies its own interval; neither source speech nor
            # body subtitles may be overwritten by the inserted static/beep.
            static_plan = replace(
                plan,
                revision=2,
                hook_transition_kind="tv_static",
                hook_transition_ms=300,
            )
            OutputCollectionRepository(root, "selected").write(
                replace(collection, plans=(static_plan, second_plan)), segments
            )
            static_result = use_case.execute(
                OutputRenderRequest(
                    root,
                    "selected",
                    "video-1",
                    segments,
                    transcript,
                    video_metadata=VideoOutputMetadata(160, 120, "25"),
                )
            )
            self.assertEqual(static_result.timeline.estimated_duration_ms, 2700)
            self.assertEqual(
                [c.output_range.start_ms for c in static_result.timeline.clips],
                [0, 1100, 1900],
            )
            static_cues = parse_srt(static_result.subtitle_path.read_text())
            self.assertEqual([c.start_ms for c in static_cues], [0, 1100, 1900])
            raw = subprocess.check_output(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-ss",
                    "0.92",
                    "-i",
                    str(static_result.output_path),
                    "-frames:v",
                    "1",
                    "-pix_fmt",
                    "rgb24",
                    "-f",
                    "rawvideo",
                    "-",
                ]
            )
            values = list(raw[::3])
            mean = sum(values) / len(values)
            self.assertGreater(sum((x - mean) ** 2 for x in values) / len(values), 100)
            audio = subprocess.check_output(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-ss",
                    "0.85",
                    "-i",
                    str(static_result.output_path),
                    "-t",
                    "0.1",
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    "8000",
                    "-f",
                    "s16le",
                    "-",
                ]
            )
            samples = array.array("h", audio)
            crossings = sum(
                (a < 0) != (b < 0) for a, b in zip(samples, samples[1:], strict=False)
            )
            self.assertTrue(
                185 <= crossings <= 215, crossings
            )  # 1 kHz tone, 0.1 seconds
            cropped_plan = replace(
                static_plan,
                revision=3,
                items=(
                    replace(
                        static_plan.items[0], source_start_ms=2100, source_end_ms=2500
                    ),
                    *static_plan.items[1:],
                ),
            )
            OutputCollectionRepository(root, "selected").write(
                replace(collection, plans=(cropped_plan, second_plan)), segments
            )
            cropped = use_case.execute(
                OutputRenderRequest(
                    root,
                    "selected",
                    "video-1",
                    segments,
                    transcript,
                    video_metadata=VideoOutputMetadata(160, 120, "25"),
                )
            )
            self.assertEqual(cropped.timeline.estimated_duration_ms, 2300)
            self.assertEqual(cropped.timeline.clips[1].source_range.start_ms, 0)
            self.assertEqual(
                parse_srt(cropped.subtitle_path.read_text())[0].end_ms, 400
            )
