import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from minicut.application import TranscribeProjectUseCase, TranscribeRequest
from minicut.media import MediaAsset, StreamInfo, StreamType
from minicut.project import ProjectManifest, ProjectRepository
from minicut.transcript import Transcript, TranscriptSource, Word


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


if __name__ == "__main__":
    unittest.main()
