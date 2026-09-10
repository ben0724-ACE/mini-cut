import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

from minicut.application import (
    EditCancelled,
    EditProgressEvent,
    EditProjectUseCase,
    EditRequest,
    InspectProjectUseCase,
    InspectRequest,
    PlanProjectUseCase,
    PlanRequest,
    PlanResult,
    RenderProjectUseCase,
    RenderRequest,
    RenderResult,
    TranscribeProjectUseCase,
    TranscribeRequest,
    TranscribeResult,
)
from minicut.edit_plan import EditBrief, EditIntensity, EditPlan
from minicut.errors import ProcessingError
from minicut.media import MediaAsset, StreamInfo, StreamType
from minicut.project import ProjectManifest, ProjectRepository
from minicut.rule_planner import RulePlanner
from minicut.semantic_segment import SemanticSegment
from minicut.transcript import Transcript, TranscriptSource, Utterance, Word
from minicut.transcription_cache import (
    TranscriptCacheRepository,
    TranscriptionCacheKey,
)
from minicut.transcription_task import CancellationToken


class TranscribeProjectUseCaseTest(unittest.TestCase):
    def test_imports_transcribes_persists_and_reuses_cached_transcript(self) -> None:
        with TemporaryDirectory() as directory:
            project_directory = Path(directory)
            ProjectRepository(project_directory).create(ProjectManifest("demo"))
            asset = MediaAsset(
                "asset-1",
                "/media/input.mov",
                1_000,
                (StreamInfo(0, StreamType.AUDIO, "aac"),),
                "fingerprint",
            )
            transcript = Transcript(
                "transcript-1",
                TranscriptSource("asset-1", "mlx-whisper", "large-v3-turbo"),
                "zh",
                (Word("word-1", "你好", 0, 500),),
            )
            transcription_calls = 0

            def importer(
                repository: ProjectRepository, source_path: str | Path
            ) -> MediaAsset:
                del repository, source_path
                return asset

            def transcriber(
                asset: MediaAsset, request: TranscribeRequest
            ) -> Transcript:
                nonlocal transcription_calls
                self.assertEqual(asset.asset_id, "asset-1")
                self.assertEqual(request.provider, "mlx")
                transcription_calls += 1
                return transcript

            use_case = TranscribeProjectUseCase(
                importer=importer,
                transcriber=transcriber,
            )
            request = TranscribeRequest(
                project_directory,
                Path("/media/input.mov"),
                "mlx",
                "large-v3-turbo",
                "zh",
            )

            first = use_case.execute(request)
            second = use_case.execute(request)

            self.assertFalse(first.reused)
            self.assertTrue(second.reused)
            self.assertEqual(first.transcript_id, second.transcript_id)
            self.assertEqual(first.word_count, 1)
            self.assertEqual(transcription_calls, 1)


class PlanProjectUseCaseTest(unittest.TestCase):
    def test_builds_segments_and_atomically_persists_rule_plan(self) -> None:
        with TemporaryDirectory() as directory:
            project_directory = Path(directory)
            ProjectRepository(project_directory).create(ProjectManifest("demo"))
            words = (
                Word("w1", "内容", 0, 400),
                Word("w2", "嗯", 500, 800),
            )
            transcript = Transcript(
                "transcript-1",
                TranscriptSource("asset-1", "mlx-whisper", "large-v3-turbo"),
                "zh",
                words,
                (
                    Utterance("u1", "内容", 0, 400, ("w1",)),
                    Utterance("u2", "嗯", 500, 800, ("w2",)),
                ),
            )
            cache = TranscriptCacheRepository(
                project_directory / ".minicut/transcripts/asset-1.json"
            )
            cache.write(
                TranscriptionCacheKey(
                    "fingerprint", "mlx-whisper", "large-v3-turbo", "zh", None
                ),
                transcript,
            )

            result = PlanProjectUseCase().execute(
                PlanRequest(
                    project_directory,
                    "asset-1",
                    1_000,
                    EditIntensity.BALANCED,
                    "concise",
                    "rule",
                )
            )

            self.assertEqual((result.kept_segments, result.deleted_segments), (1, 1))
            payload = cast(
                dict[str, object],
                json.loads(result.artifact_path.read_text(encoding="utf-8")),
            )
            self.assertEqual(payload["asset_id"], "asset-1")
            self.assertEqual(len(cast(list[object], payload["segments"])), 2)
            self.assertIsInstance(payload["plan"], dict)


class FakeTimelineRenderer:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], Path, float]] = []

    def render_to_path(
        self,
        command: tuple[str, ...],
        output_path: str | Path,
        *,
        timeout_seconds: float,
        cancellation: CancellationToken | None = None,
    ) -> object:
        del cancellation
        self.calls.append((command, Path(output_path), timeout_seconds))
        return object()


class RenderProjectUseCaseTest(unittest.TestCase):
    def test_compiles_plan_renders_media_and_writes_subtitles(self) -> None:
        with TemporaryDirectory() as directory:
            project_directory = Path(directory)
            asset = MediaAsset(
                "asset-1",
                "/media/input.mov",
                1_000,
                (
                    StreamInfo(0, StreamType.VIDEO, "h264"),
                    StreamInfo(1, StreamType.AUDIO, "aac"),
                ),
                "fingerprint",
            )
            ProjectRepository(project_directory).create(
                ProjectManifest("demo", (asset,))
            )
            transcript = Transcript(
                "transcript-1",
                TranscriptSource("asset-1", "mlx-whisper", "large-v3-turbo"),
                "zh",
                (
                    Word("w1", "内容", 0, 400),
                    Word("w2", "嗯", 500, 800),
                ),
                (
                    Utterance("u1", "内容", 0, 400, ("w1",)),
                    Utterance("u2", "嗯", 500, 800, ("w2",)),
                ),
            )
            TranscriptCacheRepository(
                project_directory / ".minicut/transcripts/asset-1.json"
            ).write(
                TranscriptionCacheKey(
                    "fingerprint", "mlx-whisper", "large-v3-turbo", "zh", None
                ),
                transcript,
            )
            PlanProjectUseCase().execute(
                PlanRequest(
                    project_directory,
                    "asset-1",
                    1_000,
                    EditIntensity.BALANCED,
                    "concise",
                    "rule",
                )
            )
            renderer = FakeTimelineRenderer()
            output_path = project_directory / "exports/result.mp4"

            result = RenderProjectUseCase(renderer=renderer).execute(
                RenderRequest(project_directory, "asset-1", output_path, 30)
            )

            self.assertEqual(result.duration_ms, 400)
            self.assertEqual(len(renderer.calls), 1)
            command, rendered_path, timeout = renderer.calls[0]
            self.assertEqual(rendered_path, output_path)
            self.assertEqual(timeout, 30)
            self.assertIn("file:///media/input.mov", command)
            self.assertEqual(
                result.subtitle_path.read_text(encoding="utf-8"),
                "1\n00:00:00,000 --> 00:00:00,400\n内容\n",
            )


class InspectProjectUseCaseTest(unittest.TestCase):
    def test_reports_artifacts_without_modifying_project(self) -> None:
        with TemporaryDirectory() as directory:
            project_directory = Path(directory)
            asset = MediaAsset(
                "asset-1",
                "/media/input.mov",
                1_000,
                (StreamInfo(0, StreamType.AUDIO, "aac"),),
                "fingerprint",
            )
            ProjectRepository(project_directory).create(
                ProjectManifest("demo", (asset,))
            )
            transcript = Transcript(
                "transcript-1",
                TranscriptSource("asset-1", "mlx-whisper", "large-v3-turbo"),
                "zh",
                (Word("w1", "内容", 0, 400),),
                (Utterance("u1", "内容", 0, 400, ("w1",)),),
            )
            TranscriptCacheRepository(
                project_directory / ".minicut/transcripts/asset-1.json"
            ).write(
                TranscriptionCacheKey(
                    "fingerprint", "mlx-whisper", "large-v3-turbo", "zh", None
                ),
                transcript,
            )
            PlanProjectUseCase().execute(
                PlanRequest(
                    project_directory,
                    "asset-1",
                    500,
                    EditIntensity.BALANCED,
                    "concise",
                    "rule",
                )
            )
            before = {
                path.relative_to(project_directory): path.read_bytes()
                for path in project_directory.rglob("*")
                if path.is_file()
            }

            result = InspectProjectUseCase().execute(
                InspectRequest(project_directory, "asset-1")
            )

            self.assertEqual(result.project_id, "demo")
            self.assertEqual(result.asset_ids, ("asset-1",))
            self.assertIsNotNone(result.selected_asset)
            selected = result.selected_asset
            assert selected is not None
            self.assertEqual(selected.transcript_word_count, 1)
            self.assertEqual(
                (selected.kept_segments, selected.deleted_segments), (1, 0)
            )
            after = {
                path.relative_to(project_directory): path.read_bytes()
                for path in project_directory.rglob("*")
                if path.is_file()
            }
            self.assertEqual(after, before)


class EditProjectUseCaseTest(unittest.TestCase):
    def test_runs_all_stages_then_reuses_their_artifacts(self) -> None:
        with TemporaryDirectory() as directory:
            project_directory = Path(directory)
            ProjectRepository(project_directory).create(ProjectManifest("demo"))
            asset = MediaAsset(
                "asset-1",
                "/media/input.mov",
                1_000,
                (
                    StreamInfo(0, StreamType.VIDEO, "h264"),
                    StreamInfo(1, StreamType.AUDIO, "aac"),
                ),
                "fingerprint",
            )
            transcript = Transcript(
                "transcript-1",
                TranscriptSource("asset-1", "mlx-whisper", "large-v3-turbo"),
                "zh",
                (Word("w1", "内容", 0, 400),),
                (Utterance("u1", "内容", 0, 400, ("w1",)),),
            )
            transcription_calls = 0
            planning_calls = 0

            def importer(
                repository: ProjectRepository, source_path: str | Path
            ) -> MediaAsset:
                del source_path
                return repository.add_asset(asset)

            def transcriber(
                asset: MediaAsset, request: TranscribeRequest
            ) -> Transcript:
                nonlocal transcription_calls
                del asset, request
                transcription_calls += 1
                return transcript

            def planner(
                request: PlanRequest,
                brief: EditBrief,
                segments: tuple[SemanticSegment, ...],
            ) -> EditPlan:
                nonlocal planning_calls
                del request
                planning_calls += 1
                return RulePlanner().plan(brief, segments)

            renderer = FakeTimelineRenderer()
            output_path = project_directory / "exports/result.mp4"
            output_path.parent.mkdir()

            class PublishingRenderer(FakeTimelineRenderer):
                def render_to_path(
                    self,
                    command: tuple[str, ...],
                    output_path: str | Path,
                    *,
                    timeout_seconds: float,
                    cancellation: CancellationToken | None = None,
                ) -> object:
                    super().render_to_path(
                        command,
                        output_path,
                        timeout_seconds=timeout_seconds,
                        cancellation=cancellation,
                    )
                    Path(output_path).write_bytes(b"video")
                    return object()

            renderer = PublishingRenderer()
            progress: list[EditProgressEvent] = []
            use_case = EditProjectUseCase(
                transcribe=TranscribeProjectUseCase(
                    importer=importer, transcriber=transcriber
                ),
                plan=PlanProjectUseCase(planner=planner),
                render=RenderProjectUseCase(renderer=renderer),
            )
            request = EditRequest(
                project_directory,
                Path("/media/input.mov"),
                "mlx",
                "large-v3-turbo",
                "zh",
                500,
                EditIntensity.BALANCED,
                "concise",
                "rule",
                output_path,
                30,
                progress.append,
            )

            first = use_case.execute(request)
            second = use_case.execute(request)

            self.assertEqual(first.reused_stages, ())
            self.assertEqual(second.reused_stages, ("transcribe", "plan", "render"))
            self.assertEqual(transcription_calls, 1)
            self.assertEqual(planning_calls, 1)
            self.assertEqual(len(renderer.calls), 1)
            self.assertEqual(
                [(event.stage, event.status) for event in progress[:6]],
                [
                    ("transcribe", "running"),
                    ("transcribe", "succeeded"),
                    ("plan", "running"),
                    ("plan", "succeeded"),
                    ("render", "running"),
                    ("render", "succeeded"),
                ],
            )
            self.assertEqual(progress[5].estimated_duration_ms, 400)
            self.assertTrue(all(event.reused for event in progress[7::2]))

    def test_cancelled_before_first_stage_calls_no_service(self) -> None:
        token = CancellationToken()
        token.cancel()
        calls = 0
        progress: list[EditProgressEvent] = []

        class UnexpectedTranscribe:
            def execute(self, request: TranscribeRequest) -> TranscribeResult:
                nonlocal calls
                del request
                calls += 1
                raise AssertionError("transcribe must not run")

        request = EditRequest(
            Path("/project"),
            Path("/media/input.mov"),
            "mlx",
            "large-v3-turbo",
            "zh",
            500,
            EditIntensity.BALANCED,
            "concise",
            "rule",
            Path("/output.mp4"),
            30,
            progress.append,
            token,
        )

        with self.assertRaises(EditCancelled):
            EditProjectUseCase(transcribe=UnexpectedTranscribe()).execute(request)

        self.assertEqual(calls, 0)
        self.assertEqual(progress[-1], EditProgressEvent("transcribe", "cancelled"))

    def test_retry_reuses_transcript_completed_before_plan_failure(self) -> None:
        with TemporaryDirectory() as directory:
            project_directory = Path(directory)
            ProjectRepository(project_directory).create(ProjectManifest("demo"))
            asset = MediaAsset(
                "asset-1",
                "/media/input.mov",
                1_000,
                (StreamInfo(0, StreamType.AUDIO, "aac"),),
                "fingerprint",
            )
            transcript = Transcript(
                "transcript-1",
                TranscriptSource("asset-1", "mlx-whisper", "large-v3-turbo"),
                "zh",
                (Word("w1", "内容", 0, 400),),
            )
            transcription_calls = 0

            def importer(
                repository: ProjectRepository, source_path: str | Path
            ) -> MediaAsset:
                del source_path
                return repository.add_asset(asset)

            def transcriber(
                asset: MediaAsset, request: TranscribeRequest
            ) -> Transcript:
                nonlocal transcription_calls
                del asset, request
                transcription_calls += 1
                return transcript

            class FailOncePlan:
                def __init__(self) -> None:
                    self.calls = 0

                def execute(self, request: PlanRequest) -> PlanResult:
                    self.calls += 1
                    if self.calls == 1:
                        raise ProcessingError("planner unavailable")
                    return PlanResult(request.asset_id, 1, 0, Path("plan.json"))

            class SuccessfulRender:
                def __init__(self) -> None:
                    self.calls = 0

                def execute(self, request: RenderRequest) -> RenderResult:
                    self.calls += 1
                    return RenderResult(
                        request.output_path,
                        request.output_path.with_suffix(".srt"),
                        400,
                    )

            plan = FailOncePlan()
            render = SuccessfulRender()
            progress: list[EditProgressEvent] = []
            use_case = EditProjectUseCase(
                transcribe=TranscribeProjectUseCase(
                    importer=importer, transcriber=transcriber
                ),
                plan=plan,
                render=render,
            )
            request = EditRequest(
                project_directory,
                Path("/media/input.mov"),
                "mlx",
                "large-v3-turbo",
                "zh",
                500,
                EditIntensity.BALANCED,
                "concise",
                "rule",
                project_directory / "result.mp4",
                30,
                progress.append,
            )

            with self.assertRaisesRegex(ProcessingError, "planner unavailable"):
                use_case.execute(request)
            result = use_case.execute(request)

            self.assertEqual(transcription_calls, 1)
            self.assertEqual(plan.calls, 2)
            self.assertEqual(render.calls, 1)
            self.assertIn("transcribe", result.reused_stages)
            self.assertIn(EditProgressEvent("plan", "failed"), progress)


if __name__ == "__main__":
    unittest.main()
