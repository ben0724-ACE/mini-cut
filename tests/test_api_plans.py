import asyncio
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

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


class PlanApiTest(unittest.TestCase):
    def test_reads_modifies_and_retrieves_plan_versions(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            project_directory = root / "demo"
            ProjectRepository(project_directory).create(ProjectManifest("demo"))
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
            app = create_app(root)

            async def requests() -> tuple[
                httpx.Response, httpx.Response, httpx.Response, httpx.Response
            ]:
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://test"
                ) as client:
                    original = await client.get("/api/projects/demo/plans/asset-1")
                    original_segments = cast(
                        list[dict[str, object]], original.json()["segments"]
                    )
                    deleted_id = next(
                        cast(str, segment["segment_id"])
                        for segment in original_segments
                        if segment["action"] == "delete"
                    )
                    modified = await client.patch(
                        "/api/projects/demo/plans/asset-1",
                        json={"restore_segment_ids": [deleted_id]},
                    )
                    versions = await client.get(
                        "/api/projects/demo/plans/asset-1/versions"
                    )
                    first = await client.get(
                        "/api/projects/demo/plans/asset-1/versions/1"
                    )
                    return original, modified, versions, first

            original, modified, versions, first = asyncio.run(requests())

            self.assertEqual(original.status_code, 200)
            self.assertEqual(original.json()["revision"], 1)
            self.assertEqual(modified.status_code, 200)
            self.assertEqual(modified.json()["revision"], 2)
            self.assertEqual(
                [segment["action"] for segment in modified.json()["segments"]],
                ["keep", "keep"],
            )
            self.assertEqual(versions.json()["revisions"], [1, 2])
            self.assertEqual(first.json()["revision"], 1)
            self.assertEqual(
                [segment["action"] for segment in first.json()["segments"]],
                ["keep", "delete"],
            )

    def test_invalid_modification_does_not_create_a_version(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            project_directory = root / "demo"
            ProjectRepository(project_directory).create(ProjectManifest("demo"))
            app = create_app(root)

            async def request() -> httpx.Response:
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://test"
                ) as client:
                    return await client.patch(
                        "/api/projects/demo/plans/missing",
                        json={"restore_segment_ids": ["unknown"]},
                    )

            response = asyncio.run(request())

            self.assertEqual(response.status_code, 400)
            self.assertFalse((project_directory / ".minicut/plans").exists())


if __name__ == "__main__":
    unittest.main()
