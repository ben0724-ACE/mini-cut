import asyncio
from pathlib import Path

import httpx
import pytest

from minicut.api import create_app
from minicut.errors import UserInputError
from minicut.highlight_brief import HighlightBrief
from minicut.media import MediaAsset
from minicut.output_repository import OutputCollectionRepository
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
            assert calls[0].boundary_version == 3

    asyncio.run(run())


def test_selection_persists_without_changing_other_outputs(tmp_path: Path) -> None:
    ProjectRepository(tmp_path / "demo").create(ProjectManifest("demo"))
    repository = OutputCollectionRepository(tmp_path / "demo", "collection")
    repository.write_highlight_result(
        {
            "collection_id": "collection",
            "asset_id": "asset",
            "outputs": [
                {"output_id": "video-1", "title": "A"},
                {"output_id": "video-2", "title": "B"},
            ],
        }
    )

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(tmp_path)),
            base_url="http://test",
        ) as client:
            path = "/api/projects/demo/highlights/collection"
            assert (
                await client.put(path + "/selection", json={"output_ids": ["video-2"]})
            ).status_code == 200
            result = (await client.get(path)).json()
            assert result["selected_output_ids"] == ["video-2"]
            assert [output["title"] for output in result["outputs"]] == ["A", "B"]
            assert (
                await client.put(path + "/selection", json={"output_ids": ["unknown"]})
            ).status_code == 400
            assert (await client.get(path)).json()["selected_output_ids"] == ["video-2"]

    asyncio.run(run())


def test_generation_rejects_untranscribed_and_persists_failure(tmp_path: Path) -> None:
    ProjectRepository(tmp_path / "demo").create(
        ProjectManifest(
            "demo",
            assets=(MediaAsset("asset", "/media/test.mov", 1000, (), "existing"),),
        )
    )

    def fail(
        project: Path, asset: str, collection: str, brief: HighlightBrief
    ) -> dict[str, object]:
        raise UserInputError("DeepSeek not configured")

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(tmp_path, highlights=fail)),
            base_url="http://test",
        ) as client:
            body = {
                "asset_id": "asset",
                "preset": "knowledge_digest",
                "count": 2,
                "min_ms": 1000,
                "max_ms": 5000,
            }
            path = "/api/projects/demo/tasks/highlights"
            assert (
                await client.post(
                    path, json=body, headers={"Idempotency-Key": "missing"}
                )
            ).status_code == 400
            transcript = tmp_path / "demo/.minicut/transcripts/asset.json"
            transcript.parent.mkdir(parents=True)
            transcript.write_text("{}")
            assert (
                await client.post(
                    path,
                    json={**body, "min_ms": 6000},
                    headers={"Idempotency-Key": "invalid"},
                )
            ).status_code == 422
            assert (
                await client.post(
                    path, json=body, headers={"Idempotency-Key": "failed"}
                )
            ).status_code == 202
            recovered = (
                await client.get("/api/projects/demo/assets/asset/highlight-task")
            ).json()
            assert recovered["status"] == "failed"
            assert recovered["error"] == "DeepSeek not configured"

    asyncio.run(run())


@pytest.mark.parametrize("saved_version", [None, 2])
def test_boundary_request_version_is_preserved_on_resume(
    tmp_path: Path, saved_version: int | None
) -> None:
    import json

    directory = tmp_path / "demo"
    ProjectRepository(directory).create(
        ProjectManifest(
            "demo", assets=(MediaAsset("asset", "/a.mp4", 1000, (), "fixture"),)
        )
    )
    cache = directory / ".minicut/transcripts/asset.json"
    cache.parent.mkdir(parents=True)
    cache.write_text("{}")
    jobs = directory / ".minicut/jobs"
    jobs.mkdir()
    request: dict[str, object] = {
        "asset_id": "asset",
        "preset": "podcast_highlights",
        "count": 1,
    }
    if saved_version is not None:
        request["boundary_version"] = saved_version
    (jobs / "old.json").write_text(
        json.dumps(
            {
                "task_id": "old",
                "kind": "highlights",
                "status": "failed",
                "resumable": True,
                "request": request,
                "result": None,
                "error": "interrupted",
            }
        )
    )
    seen: list[HighlightBrief] = []

    def generate(
        project: Path, asset: str, collection: str, brief: HighlightBrief
    ) -> dict[str, object]:
        seen.append(brief)
        return {"collection_id": collection, "asset_id": asset, "outputs": []}

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(
                app=create_app(tmp_path, highlights=generate)
            ),
            base_url="http://test",
        ) as client:
            assert (
                await client.post("/api/projects/demo/tasks/old/resume")
            ).status_code == 202
            assert seen[-1].boundary_version == saved_version
            assert (
                await client.post(
                    "/api/projects/demo/tasks/highlights",
                    json={k: v for k, v in request.items() if k != "boundary_version"},
                    headers={"Idempotency-Key": "new"},
                )
            ).status_code == 202
            assert seen[-1].boundary_version == 3
            saved = json.loads((jobs / "new.json").read_text())
            assert saved["generation_config"]["boundary_version"] == 3
            saved.update(status="failed", result=None, error="interrupted")
            (jobs / "new.json").write_text(json.dumps(saved))
            assert (
                await client.post("/api/projects/demo/tasks/new/resume")
            ).status_code == 202
            assert seen[-1].boundary_version == 3

    asyncio.run(run())
