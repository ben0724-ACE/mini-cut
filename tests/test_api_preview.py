import asyncio
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx

from minicut.api import create_app
from minicut.application import PlanProjectUseCase, PlanRequest
from minicut.edit_plan import EditIntensity
from minicut.project import ProjectManifest, ProjectRepository
from minicut.transcript import Transcript, TranscriptSource, Utterance, Word
from minicut.transcription_cache import (
    TranscriptCacheRepository,
    TranscriptionCacheKey,
)


class PreviewApiTest(unittest.TestCase):
    def test_compiles_preview_with_the_formal_render_timeline_mapping(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "demo"
            ProjectRepository(project).create(ProjectManifest("demo"))
            transcript = Transcript(
                "transcript-1",
                TranscriptSource("asset-1", "mlx-whisper", "large-v3-turbo"),
                "zh",
                (Word("w1", "内容", 100, 500), Word("w2", "嗯", 700, 900)),
                (
                    Utterance("u1", "内容", 100, 500, ("w1",)),
                    Utterance("u2", "嗯", 700, 900, ("w2",)),
                ),
            )
            TranscriptCacheRepository(
                project / ".minicut/transcripts/asset-1.json"
            ).write(
                TranscriptionCacheKey(
                    "fingerprint", "mlx-whisper", "large-v3-turbo", "zh", None
                ),
                transcript,
            )
            PlanProjectUseCase().execute(
                PlanRequest(
                    project,
                    "asset-1",
                    1_000,
                    EditIntensity.BALANCED,
                    "concise",
                    "rule",
                )
            )
            app = create_app(root)

            async def request() -> httpx.Response:
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://test"
                ) as client:
                    return await client.get("/api/projects/demo/plans/asset-1/preview")

            response = asyncio.run(request())

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["plan_revision"], 1)
            self.assertEqual(payload["estimated_duration_ms"], 400)
            self.assertEqual(len(payload["clips"]), 1)
            clip = payload["clips"][0]
            self.assertTrue(clip["segment_ids"])
            self.assertEqual(clip["source_start_ms"], 100)
            self.assertEqual(clip["source_end_ms"], 500)
            self.assertEqual(clip["output_start_ms"], 0)
            self.assertEqual(clip["output_end_ms"], 400)


if __name__ == "__main__":
    unittest.main()
