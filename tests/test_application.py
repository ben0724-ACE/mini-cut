import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

from minicut.application import (
    PlanProjectUseCase,
    PlanRequest,
    RenderProjectUseCase,
    RenderRequest,
    TranscribeProjectUseCase,
    TranscribeRequest,
)
from minicut.edit_plan import EditIntensity
from minicut.media import MediaAsset, StreamInfo, StreamType
from minicut.project import ProjectManifest, ProjectRepository
from minicut.transcript import Transcript, TranscriptSource, Utterance, Word
from minicut.transcription_cache import (
    TranscriptCacheRepository,
    TranscriptionCacheKey,
)


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

            self.assertEqual(first, second)
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
    ) -> object:
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


if __name__ == "__main__":
    unittest.main()
