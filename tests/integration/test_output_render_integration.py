import json
import shutil
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

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
from minicut.render_command import VideoOutputMetadata
from minicut.semantic_segment import SemanticSegment
from minicut.subtitle import parse_srt
from minicut.transcript import Transcript, TranscriptSource, Word


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
            for timestamp, channel in (("0.4", 2), ("1.2", 0), ("2.0", 2)):
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
                self.assertGreater(pixel[channel], 150)
                self.assertEqual(pixel.index(max(pixel)), channel)
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
