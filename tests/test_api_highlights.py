import asyncio
from pathlib import Path

import httpx

from minicut.api import create_app
from minicut.highlight_brief import HighlightBrief
from minicut.media import MediaAsset
from minicut.project import ProjectManifest, ProjectRepository


def test_highlight_tasks_are_idempotent_and_recover_shortfall(tmp_path: Path) -> None:
    calls: list[HighlightBrief] = []

    def generate(
        project: Path, asset: str, collection: str, brief: HighlightBrief
    ) -> dict[str, object]:
        calls.append(brief)
        return {
            "collection_id": collection,
            "asset_id": asset,
            "notes": ["数量不足"],
            "outputs": [],
        }

    repository = ProjectRepository(tmp_path / "demo")
    repository.create(
        ProjectManifest(
            "demo",
            assets=(MediaAsset("asset", "/media/test.mov", 1000, (), "existing"),),
        )
    )
    transcript = tmp_path / "demo/.minicut/transcripts/asset.json"
    transcript.parent.mkdir(parents=True)
    transcript.write_text("{}")

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(
                app=create_app(tmp_path, highlights=generate)
            ),
            base_url="http://test",
        ) as client:
            body = {
                "asset_id": "asset",
                "preset": "podcast_highlights",
                "count": 3,
                "min_ms": 1000,
                "max_ms": 5000,
                "instructions": "保留限定条件",
            }
            for _ in range(2):
                result = await client.post(
                    "/api/projects/demo/tasks/highlights",
                    json=body,
                    headers={"Idempotency-Key": "one"},
                )
                assert result.status_code == 202
            recovered = (
                await client.get("/api/projects/demo/assets/asset/highlight-task")
            ).json()
            assert recovered["status"] == "succeeded"
            assert recovered["result"]["notes"] == ["数量不足"]
            assert len(calls) == 1
            assert calls[0].instructions == "保留限定条件"

    asyncio.run(run())
