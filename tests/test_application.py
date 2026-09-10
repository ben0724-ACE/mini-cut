import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

from minicut.application import (
    PlanProjectUseCase,
    PlanRequest,
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


if __name__ == "__main__":
    unittest.main()
