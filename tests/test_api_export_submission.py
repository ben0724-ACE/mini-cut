import asyncio
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import NoReturn

import httpx
import pytest
from fastapi import BackgroundTasks

import minicut.api as api_module
from minicut.api import create_app
from minicut.project import ProjectManifest, ProjectRepository
from minicut.task_workers import TaskQueueFull, TaskWorkerPool


def test_batch_validates_all_covers_before_creating_tasks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ProjectRepository(tmp_path / "demo").create(ProjectManifest("demo"))
    calls: list[str] = []

    def export(*args: object) -> dict[str, object]:
        calls.append(str(args[2]))
        return {}

    monkeypatch.setattr(api_module, "export_output", export)

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(tmp_path)),
            base_url="http://test",
        ) as client:
            outputs = [
                {"collection_id": "c", "output_id": output_id, "revision": 1}
                for output_id in ("one", "two")
            ]
            route = "/api/projects/demo/tasks/output-export-batch"
            headers = {"Idempotency-Key": "batch"}
            response = await client.post(
                route,
                json={"outputs": [outputs[0], {**outputs[1], "cover_version": 999}]},
                headers=headers,
            )
            assert response.status_code == 400
            assert not list((tmp_path / "demo/.minicut/jobs").glob("*.json"))
            assert calls == []
            response = await client.post(
                route, json={"outputs": outputs}, headers=headers
            )
            assert response.status_code == 202
            assert sorted(calls) == ["one", "two"]
            await client.post(route, json={"outputs": outputs}, headers=headers)
            assert len(calls) == 2

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["create", "register", "full", "submit"])
def test_failed_batch_submission_settles_only_new_unexecuted_tasks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    ProjectRepository(tmp_path / "demo").create(ProjectManifest("demo"))
    calls: list[str] = []

    def export(*args: object) -> dict[str, object]:
        calls.append(str(args[2]))
        return {"output_id": args[2], "revision": 1}

    monkeypatch.setattr(api_module, "export_output", export)
    write_job = api_module._write_job  # pyright: ignore[reportPrivateUsage]

    def fail_create(
        path: Path, payload: dict[str, object], *, create: bool = False
    ) -> None:
        if create and path.stem == "batch-two":
            raise OSError("creation failed")
        write_job(path, payload, create=create)

    def fail_register(
        self: BackgroundTasks,
        func: Callable[..., object],
        *args: object,
        **kwargs: object,
    ) -> NoReturn:
        raise RuntimeError("registration failed")

    def fail_full(*args: object, **kwargs: object) -> NoReturn:
        raise TaskQueueFull("queue full")

    def fail_submit(
        self: TaskWorkerPool, operations: list[Callable[[], None]]
    ) -> NoReturn:
        raise RuntimeError("submission failed")

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(
                app=create_app(tmp_path), raise_app_exceptions=False
            ),
            base_url="http://test",
        ) as client:
            outputs = [
                {"collection_id": "c", "output_id": output_id, "revision": 1}
                for output_id in ("existing", "one", "two")
            ]
            await client.post(
                "/api/projects/demo/tasks/output-export",
                json=outputs[0],
                headers={"Idempotency-Key": "batch-existing"},
            )
            with monkeypatch.context() as patch:
                if failure == "create":
                    patch.setattr(api_module, "_write_job", fail_create)
                elif failure == "register":
                    patch.setattr(BackgroundTasks, "add_task", fail_register)
                elif failure == "full":
                    patch.setattr(TaskWorkerPool, "submit_many", fail_full)
                else:
                    patch.setattr(TaskWorkerPool, "submit_many", fail_submit)
                response = await client.post(
                    "/api/projects/demo/tasks/output-export-batch",
                    json={"outputs": outputs},
                    headers={"Idempotency-Key": "batch"},
                )
                # Admission now happens before sending a successful response.
                assert response.status_code == (503 if failure == "full" else 500)

            assert calls.count("existing") == 1
            assert (await client.get("/api/projects/demo/tasks/batch-existing")).json()[
                "status"
            ] == "succeeded"
            pending_ids = ("one",) if failure == "create" else ("one", "two")
            for output_id in pending_ids:
                task_id = f"batch-{output_id}"
                job = (await client.get(f"/api/projects/demo/tasks/{task_id}")).json()
                expected = "succeeded" if output_id in calls else "failed"
                assert job["status"] == expected
                if expected == "failed":
                    saved = json.loads(
                        (tmp_path / f"demo/.minicut/jobs/{task_id}.json").read_text()
                    )
                    assert saved["status"] == "failed"
                    assert saved["owner_pid"] == os.getpid()
                    assert job["resumable"] and job["error"]
                    resumed = await client.post(
                        f"/api/projects/demo/tasks/{task_id}/resume"
                    )
                    assert resumed.status_code == 202
                    assert (
                        await client.get(
                            f"/api/projects/demo/tasks/{resumed.json()['task_id']}"
                        )
                    ).json()["status"] == "succeeded"

    asyncio.run(run())


@pytest.mark.parametrize("batch", [False, True])
def test_idempotency_conflict_does_not_create_earlier_batch_tasks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, batch: bool
) -> None:
    ProjectRepository(tmp_path / "demo").create(ProjectManifest("demo"))

    def export(*args: object) -> dict[str, object]:
        return {}

    monkeypatch.setattr(api_module, "export_output", export)

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(tmp_path)),
            base_url="http://test",
        ) as client:
            output = {"collection_id": "c", "output_id": "two", "revision": 1}
            await client.post(
                "/api/projects/demo/tasks/output-export",
                json=output,
                headers={"Idempotency-Key": "batch-two"},
            )
            conflict = {**output, "revision": 2}
            if batch:
                route = "/api/projects/demo/tasks/output-export-batch"
                payload = {"outputs": [{**output, "output_id": "one"}, conflict]}
                key = "batch"
            else:
                route = "/api/projects/demo/tasks/output-export"
                payload = conflict
                key = "batch-two"
            response = await client.post(
                route, json=payload, headers={"Idempotency-Key": key}
            )
            assert response.status_code == 409
            assert not (tmp_path / "demo/.minicut/jobs/batch-one.json").exists()

    asyncio.run(run())


def test_incomplete_task_creation_does_not_leave_a_corrupt_record(
    tmp_path: Path,
) -> None:
    path = tmp_path / "task.json"
    with pytest.raises(TypeError):
        api_module._write_job(  # pyright: ignore[reportPrivateUsage]
            path, {"invalid": object()}, create=True
        )
    assert not path.exists()
    api_module._write_job(  # pyright: ignore[reportPrivateUsage]
        path, {"status": "pending"}, create=True
    )
    assert json.loads(path.read_text()) == {"status": "pending"}


def test_single_export_registration_failure_can_be_resumed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ProjectRepository(tmp_path / "demo").create(ProjectManifest("demo"))

    def export(*args: object) -> dict[str, object]:
        return {}

    def fail_register(
        self: BackgroundTasks,
        func: Callable[..., object],
        *args: object,
        **kwargs: object,
    ) -> NoReturn:
        raise RuntimeError("registration failed")

    monkeypatch.setattr(api_module, "export_output", export)

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(
                app=create_app(tmp_path), raise_app_exceptions=False
            ),
            base_url="http://test",
        ) as client:
            with monkeypatch.context() as patch:
                patch.setattr(BackgroundTasks, "add_task", fail_register)
                response = await client.post(
                    "/api/projects/demo/tasks/output-export",
                    json={"collection_id": "c", "output_id": "one", "revision": 1},
                    headers={"Idempotency-Key": "single"},
                )
                assert response.status_code == 500
            job = (await client.get("/api/projects/demo/tasks/single")).json()
            assert job["status"] == "failed" and job["resumable"]
            resumed = await client.post("/api/projects/demo/tasks/single/resume")
            assert resumed.status_code == 202
            assert (
                await client.get(
                    f"/api/projects/demo/tasks/{resumed.json()['task_id']}"
                )
            ).json()["status"] == "succeeded"

    asyncio.run(run())
