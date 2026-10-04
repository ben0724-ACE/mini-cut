import asyncio
import json
from pathlib import Path
from threading import Event

import anyio.to_thread
import httpx
import pytest

import minicut.api as api_module
from minicut.api import create_app
from minicut.application import TranscribeRequest, TranscribeResult
from minicut.project import ProjectManifest, ProjectRepository
from tests.test_workflows import definition, project


async def wait_for_job(path: Path) -> None:
    async with asyncio.timeout(3):
        while not path.is_file():
            await asyncio.sleep(0.01)


@pytest.mark.parametrize(
    "kind", ["transcribe", "output-export", "output-preview", "batch", "mixed"]
)
def test_queued_tasks_leave_http_workers_available_for_queries_and_cancellation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    ProjectRepository(tmp_path / "demo").create(ProjectManifest("demo"))
    started, release = Event(), Event()
    calls: list[str] = []

    def block(identity: str) -> None:
        calls.append(identity)
        started.set()
        assert release.wait(5)

    class Transcriber:
        def execute(self, request: TranscribeRequest) -> TranscribeResult:
            block(request.model)
            return TranscribeResult("transcript", "asset", 1)

    def export(*args: object) -> dict[str, object]:
        block(str(args[2]))
        return {"output_id": args[2], "revision": 1}

    monkeypatch.setattr(api_module, "export_output", export)
    monkeypatch.setattr(api_module, "preview_output", export)
    app = create_app(tmp_path, transcribe=Transcriber(), export_concurrency=1)

    async def run() -> None:
        limiter = anyio.to_thread.current_default_thread_limiter()
        previous = limiter.total_tokens
        limiter.total_tokens = 2
        requests: list[asyncio.Task[httpx.Response]] = []
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:

            def submit(identity: str) -> asyncio.Task[httpx.Response]:
                if kind == "transcribe":
                    body: dict[str, object] = {
                        "source_path": "/media/input.mov",
                        "provider": "whisper",
                        "model": identity,
                    }
                    route, key = kind, identity
                else:
                    body = {"collection_id": "c", "output_id": identity, "revision": 1}
                    route, key = (
                        "output-export" if kind == "mixed" else kind,
                        identity,
                    )
                    if kind == "batch" or (kind == "mixed" and identity == "waiting"):
                        body = {"outputs": [body]}
                        route, key = "output-export-batch", "batch"
                request = asyncio.create_task(
                    client.post(
                        f"/api/projects/demo/tasks/{route}",
                        json=body,
                        headers={"Idempotency-Key": key},
                    )
                )
                requests.append(request)
                return request

            try:
                submit("first")
                assert await asyncio.to_thread(started.wait, 3)
                submit("waiting")
                queued_id = "batch-waiting" if kind in {"batch", "mixed"} else "waiting"
                path = tmp_path / f"demo/.minicut/jobs/{queued_id}.json"
                await wait_for_job(path)
                assert json.loads(path.read_text())["status"] == "pending"
                response = await asyncio.wait_for(
                    client.get(f"/api/projects/demo/tasks/{queued_id}"), 1
                )
                assert response.status_code == 200
                assert response.json()["status"] == "pending"
                activity = await asyncio.wait_for(
                    client.get("/api/projects/demo/activity"), 1
                )
                assert activity.status_code == 200
                cancelled = await asyncio.wait_for(
                    client.post(f"/api/projects/demo/tasks/{queued_id}/cancel"), 1
                )
                assert cancelled.status_code == 200
                assert cancelled.json()["status"] == "cancelled"
                assert not release.is_set()
            finally:
                release.set()
                await asyncio.gather(*requests, return_exceptions=True)
                limiter.total_tokens = previous
            assert calls == ["first"]

    asyncio.run(run())


def test_queued_workflow_can_cancel_before_a_coordinator_is_available(
    tmp_path: Path,
) -> None:
    project(tmp_path)
    assets = ProjectRepository(tmp_path / "demo").read().assets
    for identity in ("second", "third"):
        ProjectRepository(tmp_path / identity).create(
            ProjectManifest(identity, assets=assets)
        )
    started, release = Event(), Event()

    class Transcriber:
        def execute(self, request: TranscribeRequest) -> TranscribeResult:
            started.set()
            assert release.wait(5)
            assert request.cancellation is not None
            request.cancellation.raise_if_cancelled()
            return TranscribeResult("transcript", "asset", 1)

    app = create_app(tmp_path, transcribe=Transcriber(), task_queue_capacity=1)

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            saved = (await client.post("/api/workflows", json=definition())).json()
            body = {"asset_id": "asset", "workflow_id": saved["workflow_id"]}
            requests: list[asyncio.Task[httpx.Response]] = []

            def submit(identity: str) -> asyncio.Task[httpx.Response]:
                request = asyncio.create_task(
                    client.post(
                        f"/api/projects/{identity}/workflow-runs",
                        json=body,
                        headers={"Idempotency-Key": "run"},
                    )
                )
                requests.append(request)
                return request

            try:
                submit("demo")
                assert await asyncio.to_thread(started.wait, 3)
                submit("second")
                await wait_for_job(
                    tmp_path / "second/.minicut/jobs/workflow-run-run-transcribe.json"
                )
                third = submit("third")
                await wait_for_job(
                    tmp_path / "third/.minicut/jobs/workflow-run-run.json"
                )
                # A duplicate goes through the route lock after admission.
                assert (
                    await client.post(
                        "/api/projects/third/workflow-runs",
                        json=body,
                        headers={"Idempotency-Key": "run"},
                    )
                ).status_code == 202
                cancelled = await asyncio.wait_for(
                    client.post(
                        "/api/projects/third/workflow-runs/workflow-run-run/cancel"
                    ),
                    1,
                )
                assert cancelled.json()["status"] == "cancelled"
                assert (await asyncio.wait_for(third, 1)).status_code == 202
                assert not release.is_set()
            finally:
                for identity in ("demo", "second"):
                    await client.post(
                        f"/api/projects/{identity}/workflow-runs/workflow-run-run/cancel"
                    )
                release.set()
                await asyncio.gather(*requests)

    asyncio.run(run())


@pytest.mark.parametrize("batch", [False, True])
def test_full_queue_fails_admission_and_cancel_frees_capacity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, batch: bool
) -> None:
    ProjectRepository(tmp_path / "demo").create(ProjectManifest("demo"))
    started, release = Event(), Event()
    calls: list[str] = []

    def export(*args: object) -> dict[str, object]:
        identity = str(args[2])
        calls.append(identity)
        if identity == "first":
            started.set()
            assert release.wait(5)
        return {"output_id": identity, "revision": 1}

    monkeypatch.setattr(api_module, "export_output", export)
    app = create_app(tmp_path, export_concurrency=1, task_queue_capacity=1)

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:

            def submit(identity: str) -> asyncio.Task[httpx.Response]:
                return asyncio.create_task(
                    client.post(
                        "/api/projects/demo/tasks/output-export",
                        json={
                            "collection_id": "c",
                            "output_id": identity,
                            "revision": 1,
                        },
                        headers={"Idempotency-Key": identity},
                    )
                )

            requests = [submit("first")]
            try:
                assert await asyncio.to_thread(started.wait, 3)
                requests.append(submit("waiting"))
                await wait_for_job(tmp_path / "demo/.minicut/jobs/waiting.json")
                # Reusing an accepted idempotency key requires no new queue slot.
                duplicate = await asyncio.wait_for(submit("waiting"), 1)
                assert duplicate.status_code == 202
                assert duplicate.json()["status"] == "pending"
                overflow = {
                    "collection_id": "c",
                    "output_id": "overflow",
                    "revision": 1,
                }
                rejected = await asyncio.wait_for(
                    client.post(
                        "/api/projects/demo/tasks/"
                        + ("output-export-batch" if batch else "output-export"),
                        json={"outputs": [overflow]} if batch else overflow,
                        headers={"Idempotency-Key": "overflow"},
                    ),
                    1,
                )
                assert rejected.status_code == 503
                rejected_id = "overflow-overflow" if batch else "overflow"
                job = (
                    await client.get(f"/api/projects/demo/tasks/{rejected_id}")
                ).json()
                assert job["status"] == "failed" and job["resumable"]
                await client.post("/api/projects/demo/tasks/waiting/cancel")
                requests.append(submit("replacement"))
                await wait_for_job(tmp_path / "demo/.minicut/jobs/replacement.json")
            finally:
                release.set()
                responses = await asyncio.gather(*requests)
            assert all(response.status_code == 202 for response in responses)
            assert calls == ["first", "replacement"]

    asyncio.run(run())


def test_workflow_waiting_for_compute_leaves_management_routes_available(
    tmp_path: Path,
) -> None:
    project(tmp_path)
    started, release = Event(), Event()

    class Transcriber:
        def execute(self, request: TranscribeRequest) -> TranscribeResult:
            started.set()
            assert release.wait(5)
            assert request.cancellation is not None
            request.cancellation.raise_if_cancelled()
            return TranscribeResult("transcript", "asset", 1)

    app = create_app(tmp_path, transcribe=Transcriber())

    async def run() -> None:
        limiter = anyio.to_thread.current_default_thread_limiter()
        previous = limiter.total_tokens
        limiter.total_tokens = 2
        requests: list[asyncio.Task[httpx.Response]] = []
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            saved = (await client.post("/api/workflows", json=definition())).json()
            requests.append(
                asyncio.create_task(
                    client.post(
                        "/api/projects/demo/tasks/transcribe",
                        json={
                            "asset_id": "asset",
                            "provider": "whisper",
                            "model": "tiny",
                        },
                        headers={"Idempotency-Key": "blocking"},
                    )
                )
            )
            try:
                assert await asyncio.to_thread(started.wait, 3)
                # The workflow uses a different project so its duplicate check
                # permits a child waiting behind the shared compute worker.
                other = ProjectRepository(tmp_path / "other")
                other.create(
                    ProjectManifest(
                        "other",
                        assets=ProjectRepository(tmp_path / "demo").read().assets,
                    )
                )
                requests.append(
                    asyncio.create_task(
                        client.post(
                            "/api/projects/other/workflow-runs",
                            json={
                                "asset_id": "asset",
                                "workflow_id": saved["workflow_id"],
                            },
                            headers={"Idempotency-Key": "queued"},
                        )
                    )
                )
                await wait_for_job(
                    tmp_path / "other/.minicut/jobs/workflow-run-queued-transcribe.json"
                )
                latest = await asyncio.wait_for(
                    client.get("/api/projects/other/workflow-run"), 1
                )
                assert latest.json()["status"] == "running"
                cancelled = await asyncio.wait_for(
                    client.post(
                        "/api/projects/other/workflow-runs/workflow-run-queued/cancel"
                    ),
                    1,
                )
                assert cancelled.status_code == 200
                await client.post("/api/projects/demo/tasks/blocking/cancel")
            finally:
                release.set()
                await asyncio.gather(*requests)
                limiter.total_tokens = previous
            assert (await client.get("/api/projects/other/workflow-run")).json()[
                "status"
            ] == "cancelled"

    asyncio.run(run())
