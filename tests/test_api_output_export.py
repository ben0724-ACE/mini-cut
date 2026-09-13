import asyncio
from pathlib import Path
from threading import Event

import httpx
import pytest

import minicut.api as api_module
from minicut.api import create_app
from minicut.errors import ProcessingError
from minicut.project import ProjectManifest, ProjectRepository
from minicut.transcription_task import CancellationToken, TranscriptionCancelled


def test_running_export_can_be_cancelled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ProjectRepository(tmp_path / "demo").create(ProjectManifest("demo"))
    started, release = Event(), Event()

    def fake_export(*args: object) -> dict[str, object]:
        token = args[-1]
        assert isinstance(token, CancellationToken)
        started.set()
        assert release.wait(3)
        token.raise_if_cancelled()
        return {}

    monkeypatch.setattr(api_module, "export_output", fake_export)

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(tmp_path)),
            base_url="http://test",
        ) as client:
            request = asyncio.create_task(
                client.post(
                    "/api/projects/demo/tasks/output-export",
                    json={"collection_id": "c", "output_id": "o", "revision": 1},
                    headers={"Idempotency-Key": "cancel-me"},
                )
            )
            assert await asyncio.to_thread(started.wait, 3)
            try:
                response = await client.post(
                    "/api/projects/demo/tasks/cancel-me/cancel"
                )
                assert response.status_code == 200
            finally:
                release.set()
            await request
            job = (await client.get("/api/projects/demo/tasks/cancel-me")).json()
            assert job["status"] == "cancelled" and job["result"] is None

    asyncio.run(run())


@pytest.mark.parametrize("outcome", ["success", "failure", "cancelled"])
def test_output_export_configuration_recovery_and_terminal_downloads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    ProjectRepository(tmp_path / "demo").create(ProjectManifest("demo"))
    calls: list[tuple[object, ...]] = []

    def fake_export(*args: object) -> dict[str, object]:
        calls.append(args)
        if outcome == "failure":
            raise ProcessingError("render failed")
        if outcome == "cancelled":
            raise TranscriptionCancelled("cancelled")
        return {"media_url": "/video", "subtitle_url": "/subtitle", "revision": 2}

    monkeypatch.setattr(api_module, "export_output", fake_export)

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(tmp_path)),
            base_url="http://test",
        ) as client:
            payload = {"collection_id": "c", "output_id": "o", "revision": 2}
            route = "/api/projects/demo/tasks/output-export"
            response = await client.post(
                route, json=payload, headers={"Idempotency-Key": "single"}
            )
            assert response.status_code == 202
            job = (await client.get("/api/projects/demo/tasks/single")).json()
            assert (
                job["status"]
                == {
                    "success": "succeeded",
                    "failure": "failed",
                    "cancelled": "cancelled",
                }[outcome]
            )
            assert (job["result"] is not None) == (outcome == "success")
            recovered = (
                await client.get(
                    "/api/projects/demo/highlights/c/outputs/o/export-task"
                )
            ).json()
            assert recovered == job
            assert (
                await client.post("/api/projects/demo/tasks/single/cancel")
            ).json() == job
            await client.post(
                route, json=payload, headers={"Idempotency-Key": "single"}
            )
            assert len(calls) == 1
            assert calls[0][5:8] == ("soft", 0, "none")
            assert (
                await client.post(
                    route,
                    json={**payload, "denoiser_id": "unsafe"},
                    headers={"Idempotency-Key": "bad"},
                )
            ).status_code == 422

    asyncio.run(run())
