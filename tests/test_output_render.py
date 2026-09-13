import json
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from minicut.errors import ProcessingError, UserInputError
from minicut.media import MediaAsset, StreamInfo, StreamType
from minicut.output_plan import (
    HighlightCandidate,
    OutputCollection,
    OutputItem,
    OutputPlan,
    OutputRole,
)
from minicut.output_render import OutputRenderRequest, RenderOutputUseCase
from minicut.output_repository import OutputCollectionRepository
from minicut.project import ProjectManifest, ProjectRepository
from minicut.render_command import VideoOutputMetadata
from minicut.semantic_segment import SemanticSegment
from minicut.transcript import Transcript, TranscriptSource, Word


class FakeRenderer:
    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []
        self.fail_subtitle = False

    def render_to_path(
        self,
        command: tuple[str, ...],
        output_path: str | Path,
        *,
        timeout_seconds: float,
        cancellation: object = None,
    ) -> object:
        del timeout_seconds, cancellation
        self.commands.append(command)
        if self.fail_subtitle and "mov_text" in command:
            raise ProcessingError("subtitle failed")
        Path(output_path).write_bytes(b"complete")
        return object()


class OutputRenderTest(unittest.TestCase):
    def test_independent_revisions_rerender_without_ai_and_failure_preserves_output(
        self,
    ) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.mp4"
            source.write_bytes(b"original")
            asset = MediaAsset(
                "asset",
                str(source),
                3000,
                (
                    StreamInfo(0, StreamType.VIDEO, "h264"),
                    StreamInfo(1, StreamType.AUDIO, "aac"),
                ),
                "existing",
            )
            ProjectRepository(root).create(ProjectManifest("demo", (asset,)))
            segments = (
                SemanticSegment("a", "背景。", 0, 800, ("ua",), ("wa",)),
                SemanticSegment("c", "结论。", 2000, 2800, ("uc",), ("wc",)),
            )
            transcript = Transcript(
                "t",
                TranscriptSource("asset", "test", "test"),
                "zh",
                (Word("wa", "背景。", 0, 800), Word("wc", "结论。", 2000, 2800)),
            )
            plan = OutputPlan(
                "video",
                "candidate",
                "title",
                (
                    OutputItem("hook-c", "c", OutputRole.HOOK),
                    OutputItem("body-a", "a", OutputRole.BODY),
                    OutputItem("body-c", "c", OutputRole.BODY),
                ),
            )
            collection = OutputCollection(
                "selected",
                "asset",
                (HighlightCandidate("candidate", "title", "reason", ("a", "c")),),
                (plan,),
            )
            repo = OutputCollectionRepository(root, "selected")
            repo.write(collection, segments)
            renderer = FakeRenderer()
            use_case = RenderOutputUseCase(renderer=renderer)
            request = OutputRenderRequest(
                root, "selected", "video", segments, transcript
            )
            for invalid in (
                replace(request, timeout_seconds=0),
                replace(request, output_id="missing"),
                replace(
                    request,
                    transcript=replace(
                        transcript, source=TranscriptSource("other", "test", "test")
                    ),
                ),
            ):
                with self.subTest(invalid=invalid), self.assertRaises(UserInputError):
                    use_case.execute(invalid)
            self.assertEqual(renderer.commands, [])
            first = use_case.execute(request)
            self.assertEqual(first.timeline.estimated_duration_ms, 2400)
            self.assertIn("concat=n=3", " ".join(renderer.commands[0]))
            self.assertIn("mov_text", renderer.commands[1])
            self.assertEqual(first.output_path.read_bytes(), b"complete")
            self.assertTrue(first.record_path.is_file())
            self.assertEqual(use_case.execute(request).output_path, first.output_path)
            self.assertEqual(len(renderer.commands), 4)
            independent = use_case.execute(
                replace(
                    request,
                    export_id="export-1",
                    audio_fade_ms=20,
                    denoiser_id="afftdn",
                )
            )
            self.assertNotEqual(independent.output_path, first.output_path)
            self.assertTrue(independent.record_path.is_file())
            self.assertIn("afftdn", " ".join(renderer.commands[-2]))
            self.assertIn("afade", " ".join(renderer.commands[-2]))
            portrait = use_case.execute(
                replace(
                    request,
                    export_id="portrait",
                    video_metadata=VideoOutputMetadata(720, 1280, fit="crop"),
                )
            )
            self.assertNotEqual(portrait.output_path, independent.output_path)
            self.assertIn("crop=720:1280", " ".join(renderer.commands[-2]))
            self.assertEqual(
                json.loads(portrait.record_path.read_text())["video_metadata"]["fit"],
                "crop",
            )
            renderer.fail_subtitle = True
            saved_subtitles = first.subtitle_path.read_text(encoding="utf-8")
            with self.assertRaises(ProcessingError):
                use_case.execute(request)
            self.assertEqual(first.output_path.read_bytes(), b"complete")
            self.assertEqual(
                first.subtitle_path.read_text(encoding="utf-8"), saved_subtitles
            )
            self.assertEqual(list(first.output_path.parent.glob(".render-*")), [])
            self.assertEqual(source.read_bytes(), b"original")
            renderer.fail_subtitle = False
            revised = replace(plan, revision=2, title="second version")
            repo.write(replace(collection, plans=(revised,)), segments)
            second = use_case.execute(request)
            self.assertNotEqual(second.output_path, first.output_path)
            self.assertNotEqual(second.record_path, first.record_path)
            record = json.loads(first.record_path.read_text(encoding="utf-8"))
            self.assertEqual(record["plan"]["revision"], 1)
            self.assertEqual(source.read_bytes(), b"original")
            repo.write(
                replace(
                    collection,
                    plans=(replace(revised, title="changed without revision"),),
                ),
                segments,
            )
            with self.assertRaisesRegex(ValueError, "revision"):
                use_case.execute(request)
