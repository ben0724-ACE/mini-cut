import asyncio
from pathlib import Path

import httpx

from minicut.api import create_app
from minicut.application import TranscribeRequest, TranscribeResult
from minicut.media import MediaAsset
from minicut.project import ProjectManifest, ProjectRepository


def test_transcribe_registered_asset_and_recover_task(tmp_path: Path) -> None:
    class Transcriber:
        def execute(self, request: TranscribeRequest) -> TranscribeResult:
            assert request.source_path == Path("/media/registered.mov")
            return TranscribeResult("transcript", "asset", 47)

    repository = ProjectRepository(tmp_path / "demo")
    repository.create(
        ProjectManifest(
            "demo",
            assets=(
                MediaAsset("asset", "/media/registered.mov", 1000, (), "existing"),
            ),
        )
    )

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(
                app=create_app(tmp_path, transcribe=Transcriber())
            ),
            base_url="http://test",
        ) as client:
            result = await client.post(
                "/api/projects/demo/tasks/transcribe",
                headers={"Idempotency-Key": "job"},
                json={
                    "asset_id": "asset",
                    "provider": "mlx",
                    "model": "large-v3-turbo",
                },
            )
            assert result.status_code == 202
            recovered = await client.get(
                "/api/projects/demo/assets/asset/transcription-task"
            )
            assert recovered.json()["status"] == "succeeded"
            assert recovered.json()["result"]["word_count"] == 47
            invalid = await client.post(
                "/api/projects/demo/tasks/transcribe",
                headers={"Idempotency-Key": "bad"},
                json={
                    "asset_id": "missing",
                    "provider": "mlx",
                    "model": "large-v3-turbo",
                },
            )
            assert invalid.status_code == 404

    asyncio.run(run())
