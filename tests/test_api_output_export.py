import asyncio
from pathlib import Path
from threading import Event, Lock

import httpx
import pytest

import minicut.api as api_module
from minicut.api import create_app
from minicut.errors import ProcessingError
from minicut.project import ProjectManifest, ProjectRepository
from minicut.transcription_task import CancellationToken, TranscriptionCancelled


@pytest.mark.parametrize("failed", [False, True])
def test_preview_recovery_is_revision_specific(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failed: bool
) -> None:
    ProjectRepository(tmp_path / "demo").create(ProjectManifest("demo"))
    calls: list[tuple[object, ...]] = []

    def preview(*args: object) -> dict[str, object]:
        calls.append(args)
        if failed:
            raise ProcessingError("preview failed")
        return {
            "revision": 2,
            "media_url": "/cut.mp4",
            "render_engine_version": api_module.RENDER_ENGINE_VERSION,
        }

    monkeypatch.setattr(api_module, "preview_output", preview)

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(tmp_path)),
            base_url="http://test",
        ) as client:
            route = "/api/projects/demo/tasks/output-preview"
            payload = {"collection_id": "c", "output_id": "o", "revision": 2}
            await client.post(
                route, json=payload, headers={"Idempotency-Key": "preview"}
            )
            recovered = await client.get(
                "/api/projects/demo/highlights/c/outputs/o/preview-task?revision=2"
            )
            assert recovered.json()["status"] == ("failed" if failed else "succeeded")
            assert (recovered.json()["result"] is None) == failed
            assert (
                await client.get(
                    "/api/projects/demo/highlights/c/outputs/o/preview-task?revision=1"
                )
            ).json() is None
            await client.post(
                route, json=payload, headers={"Idempotency-Key": "preview"}
            )
            assert len(calls) == 1
            if not failed:
                monkeypatch.setattr(api_module, "RENDER_ENGINE_VERSION", 999)
                assert (
                    await client.get(
                        "/api/projects/demo/highlights/c/outputs/o/preview-task?revision=2"
                    )
                ).json() is None

    asyncio.run(run())


def test_batch_exports_are_independent_and_failed_output_can_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ProjectRepository(tmp_path / "demo").create(ProjectManifest("demo"))
    calls: list[str] = []

    def fake_export(*args: object) -> dict[str, object]:
        output = str(args[2])
        calls.append(output)
        if output == "bad" and calls.count("bad") == 1:
            raise ProcessingError("failed output")
        return {
            "output_id": output,
            "media_url": "/video",
            "subtitle_url": "/srt",
            "revision": 1,
        }

    monkeypatch.setattr(api_module, "export_output", fake_export)

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(tmp_path)),
            base_url="http://test",
        ) as client:
            outputs = [
                {"collection_id": "c", "output_id": id, "revision": 1}
                for id in ("good", "bad")
            ]
            route = "/api/projects/demo/tasks/output-export-batch"
            response = await client.post(
                route, json={"outputs": outputs}, headers={"Idempotency-Key": "batch"}
            )
            assert response.status_code == 202
            rows = [
                (await client.get(f"/api/projects/demo/tasks/batch-{id}")).json()
                for id in ("good", "bad")
            ]
            assert [row["status"] for row in rows] == ["succeeded", "failed"]
            assert rows[1]["result"] is None
            await client.post(
                "/api/projects/demo/tasks/output-export",
                json=outputs[1],
                headers={"Idempotency-Key": "retry"},
            )
            assert (await client.get("/api/projects/demo/tasks/retry")).json()[
                "status"
            ] == "succeeded"
            assert sorted(calls[:2]) == ["bad", "good"]
            assert calls[2] == "bad"
            assert (
                await client.post(
                    route,
                    json={"outputs": [outputs[0], outputs[0]]},
                    headers={"Idempotency-Key": "duplicate"},
                )
            ).status_code == 422

    asyncio.run(run())


def test_batch_exports_run_in_parallel_with_configured_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ProjectRepository(tmp_path / "demo").create(ProjectManifest("demo"))
    output_ids = ("one", "two", "three")
    releases = {output_id: Event() for output_id in output_ids}
    two_started, third_started = Event(), Event()
    state_lock = Lock()
    started: list[str] = []
    active = 0
    max_active = 0

    def fake_export(*args: object) -> dict[str, object]:
        nonlocal active, max_active
        output_id = str(args[2])
        with state_lock:
            started.append(output_id)
            active += 1
            max_active = max(max_active, active)
            if len(started) == 2:
                two_started.set()
            elif len(started) == 3:
                third_started.set()
        try:
            assert releases[output_id].wait(3)
            return {"output_id": output_id, "revision": 1}
        finally:
            with state_lock:
                active -= 1

    monkeypatch.setattr(api_module, "export_output", fake_export)

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(
                app=create_app(tmp_path, export_concurrency=2)
            ),
            base_url="http://test",
        ) as client:
            request = asyncio.create_task(
                client.post(
                    "/api/projects/demo/tasks/output-export-batch",
                    json={
                        "outputs": [
                            {
                                "collection_id": "c",
                                "output_id": output_id,
                                "revision": 1,
                            }
                            for output_id in output_ids
                        ]
                    },
                    headers={"Idempotency-Key": "parallel"},
                )
            )
            try:
                assert await asyncio.to_thread(two_started.wait, 3)
                with state_lock:
                    first_wave = tuple(started)
                    assert len(first_wave) == 2
                    assert active == 2
                    assert max_active == 2

                releases[first_wave[0]].set()
                assert await asyncio.to_thread(third_started.wait, 3)
                with state_lock:
                    assert len(started) == 3
                    assert active == 2
                    assert max_active == 2
            finally:
                for release in releases.values():
                    release.set()

            response = await request
            assert response.status_code == 202
            for output_id in output_ids:
                job = (
                    await client.get(f"/api/projects/demo/tasks/parallel-{output_id}")
                ).json()
                assert job["status"] == "succeeded"

    asyncio.run(run())


def test_export_concurrency_is_reported_and_validated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ProjectRepository(tmp_path / "demo").create(ProjectManifest("demo"))
    monkeypatch.setenv("MINICUT_EXPORT_CONCURRENCY", "3")

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(tmp_path)),
            base_url="http://test",
        ) as client:
            activity = (await client.get("/api/projects/demo/activity")).json()
            assert activity["heavy_task_concurrency"] == 1
            assert activity["export_task_concurrency"] == 3

    asyncio.run(run())

    for invalid in (0, 5):
        with pytest.raises(ValueError, match="integer from 1 to 4"):
            create_app(tmp_path, export_concurrency=invalid)

    monkeypatch.setenv("MINICUT_EXPORT_CONCURRENCY", "invalid")
    with pytest.raises(ValueError, match="integer from 1 to 4"):
        create_app(tmp_path)


def test_running_export_can_be_cancelled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ProjectRepository(tmp_path / "demo").create(ProjectManifest("demo"))
    started, release = Event(), Event()

    def fake_export(*args: object) -> dict[str, object]:
        token = args[8]
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
