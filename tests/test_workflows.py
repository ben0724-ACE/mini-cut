"""Minimal mode reuses tasks, preserves snapshots and recovers without duplicate AI."""

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from threading import Event
from typing import NoReturn

import httpx
import pytest
from fastapi import BackgroundTasks

from minicut.api import HighlightTaskBody, create_app
from minicut.application import TranscribeRequest, TranscribeResult
from minicut.errors import UserInputError
from minicut.highlight_brief import HighlightBrief
from minicut.highlight_service import read_highlights, source_segments
from minicut.media import MediaAsset
from minicut.output_plan import (
    HighlightCandidate,
    OutputCollection,
    OutputItem,
    OutputPlan,
    OutputRole,
)
from minicut.output_repository import OutputCollectionRepository
from minicut.project import ProjectManifest, ProjectRepository
from minicut.task_executor import TaskExecutor, TaskRunner
from minicut.task_workers import TaskQueueFull, TaskWorkerPool
from minicut.transcript import Transcript, TranscriptSource, Word
from minicut.workflows import JsonObject, WorkflowBody, WorkflowLibrary
from tests.test_generation_presets import configuration


def definition(**changes: object) -> dict[str, object]:
    return {
        "name": "AI 播客",
        "generation": configuration(),
        "transcription": {"provider": "whisper", "model": "tiny", "language": "en"},
        "export_options": {
            "aspect_ratio": "9:16",
            "resolution": 720,
            "subtitle_mode": "burned",
        },
        "layout": {"subtitle_source_scale": 1.2, "hook_transition_ms": 500},
        **changes,
    }


def project(root: Path) -> Path:
    directory = root / "demo"
    ProjectRepository(directory).create(
        ProjectManifest(
            "demo",
            assets=(
                MediaAsset("asset", str(directory / "source.mp4"), 5000, (), "test"),
            ),
        )
    )
    return directory


class Transcriber:
    def __init__(self) -> None:
        self.calls: list[TranscribeRequest] = []

    def execute(self, request: TranscribeRequest) -> TranscribeResult:
        self.calls.append(request)
        transcript = Transcript(
            "t",
            TranscriptSource("asset", request.provider, request.model),
            request.language,
            (Word("w", "Hello world.", 0, 1800),),
        )
        cache = request.project_directory / ".minicut/transcripts/asset.json"
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"transcript": transcript.to_dict()}))
        return TranscribeResult(
            transcript_id="t", asset_id="asset", word_count=1, reused=False
        )


def generator(
    calls: list[HighlightBrief], failures: int = 0, empty: bool = False
) -> Callable[[Path, str, str, HighlightBrief], dict[str, object]]:
    def generate(
        directory: Path, asset: str, collection: str, brief: HighlightBrief
    ) -> dict[str, object]:
        calls.append(brief)
        if len(calls) <= failures:
            raise UserInputError("模拟模型阶段失败")
        repo = OutputCollectionRepository(directory, collection)
        result: dict[str, object] = {
            "collection_id": collection,
            "asset_id": asset,
            "brief": brief.to_dict(),
            "notes": [],
            "outputs": [],
        }
        if not empty:
            segments = source_segments(directory, asset)
            plan = OutputPlan(
                "o",
                "c",
                "Hello",
                (OutputItem("i", segments[0].segment_id, OutputRole.BODY),),
            )
            repo.write(
                OutputCollection(
                    collection,
                    asset,
                    (
                        HighlightCandidate(
                            "c", "Hello", "理由", (segments[0].segment_id,)
                        ),
                    ),
                    (plan,),
                ),
                segments,
            )
            result["outputs"] = [{"output_id": "o", "title": "Hello", "reason": "理由"}]
        repo.write_highlight_result(result)
        return read_highlights(directory, collection)

    return generate


def test_workflow_library_snapshots_shared_presets_and_validates(
    tmp_path: Path,
) -> None:
    library = WorkflowLibrary(tmp_path)
    assert library.list() == []
    assert not library.path.exists()
    body = WorkflowBody.model_validate(definition())
    saved = library.save(body)
    assert saved["generation"]["count"] == 2

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(tmp_path)),
            base_url="http://test",
        ) as client:
            assert (await client.get("/api/workflows")).json() == [saved]
            assert (
                await client.post("/api/workflows", json=definition(name=" AI 播客 "))
            ).status_code == 409
            assert (
                await client.post(
                    "/api/workflows",
                    json=definition(generation={**configuration(), "count": 0}),
                )
            ).status_code == 422
            assert (
                await client.post(
                    "/api/workflows",
                    json=definition(layout={"subtitle_source_scale": 20}),
                )
            ).status_code == 422
            path = f"/api/workflows/{saved['workflow_id']}"
            renamed = (await client.patch(path, json={"name": "改名"})).json()
            assert renamed["generation"] == saved["generation"]
            assert (
                await client.put(path, json=definition(name="改名", auto_export=True))
            ).json()["auto_export"] is True
            assert (await client.delete(path)).status_code == 200
            assert (await client.delete(path)).status_code == 404

    asyncio.run(run())


@pytest.mark.parametrize("empty", [False, True])
def test_one_click_reuses_tasks_idempotency_and_applies_saved_settings(
    tmp_path: Path, empty: bool
) -> None:
    project(tmp_path)
    transcription = Transcriber()
    calls: list[HighlightBrief] = []
    app = create_app(
        tmp_path, transcribe=transcription, highlights=generator(calls, empty=empty)
    )

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            saved = (await client.post("/api/workflows", json=definition())).json()
            body = {"asset_id": "asset", "workflow_id": saved["workflow_id"]}
            headers = {"Idempotency-Key": "first"}
            assert (
                await client.post(
                    "/api/projects/demo/workflow-runs", json=body, headers=headers
                )
            ).status_code == 202
            completed = (await client.get("/api/projects/demo/workflow-run")).json()
            assert completed["status"] == "succeeded", completed["error"]
            assert len(calls) == len(transcription.calls) == 1
            assert transcription.calls[0].language == "en"
            assert calls[0].editing_prompt == "完整的知识解释\n\n保留例子和限定条件"
            assert calls[0].boundary_version == 3
            if not empty:
                output = completed["result"]["outputs"][0]
                assert output["subtitle_source_scale"] == 1.2
                assert output["hook_transition_ms"] == 500
                route = f"/api/projects/demo/highlights/{completed['result']['collection_id']}/outputs/o/export-settings"
                assert (await client.get(route)).json()["draft"]["options"][
                    "aspect_ratio"
                ] == "9:16"
            else:
                assert completed["result"]["outputs"] == []
            repeated = (
                await client.post(
                    "/api/projects/demo/workflow-runs", json=body, headers=headers
                )
            ).json()
            assert repeated["task_id"] == completed["task_id"]
            assert len(calls) == 1
            assert (
                await client.post(
                    "/api/projects/demo/workflow-runs",
                    json={**body, "workflow_id": "other"},
                    headers=headers,
                )
            ).status_code == 409

    asyncio.run(run())


def test_failed_generation_recovers_twice_reusing_transcription_and_original_workflow(
    tmp_path: Path,
) -> None:
    project(tmp_path)
    transcription = Transcriber()
    calls: list[HighlightBrief] = []

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(
                app=create_app(
                    tmp_path,
                    transcribe=transcription,
                    highlights=generator(calls, failures=2),
                )
            ),
            base_url="http://test",
        ) as client:
            saved = (await client.post("/api/workflows", json=definition())).json()
            task = (
                await client.post(
                    "/api/projects/demo/workflow-runs",
                    json={"asset_id": "asset", "workflow_id": saved["workflow_id"]},
                    headers={"Idempotency-Key": "failed"},
                )
            ).json()
            assert (await client.get("/api/projects/demo/workflow-run")).json()[
                "status"
            ] == "failed"
            # Remove the template: recovery still uses the submitted snapshot.
            await client.delete(f"/api/workflows/{saved['workflow_id']}")
            for _ in range(2):
                response = await client.post(
                    f"/api/projects/demo/workflow-runs/{task['task_id']}/resume"
                )
                assert response.status_code == 202, response.text
            latest = (await client.get("/api/projects/demo/workflow-run")).json()
            assert latest["status"] == "succeeded", latest["error"]
            assert len(transcription.calls) == 1
            assert len(calls) == 3
            assert all(call == calls[0] for call in calls)

    asyncio.run(run())


@pytest.mark.parametrize("cancel_route", ["workflow-runs", "tasks"])
def test_cancel_and_mode_independent_duplicate_start(
    tmp_path: Path, cancel_route: str
) -> None:
    project(tmp_path)
    started = Event()
    release = Event()
    calls: list[HighlightBrief] = []

    class BlockingTranscriber(Transcriber):
        def execute(self, request: TranscribeRequest) -> TranscribeResult:
            started.set()
            release.wait(5)
            assert request.cancellation is not None
            request.cancellation.raise_if_cancelled()
            return super().execute(request)

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(
                app=create_app(
                    tmp_path,
                    transcribe=BlockingTranscriber(),
                    highlights=generator(calls),
                )
            ),
            base_url="http://test",
        ) as client:
            saved = (await client.post("/api/workflows", json=definition())).json()
            body = {"asset_id": "asset", "workflow_id": saved["workflow_id"]}
            pending = asyncio.create_task(
                client.post(
                    "/api/projects/demo/workflow-runs",
                    json=body,
                    headers={"Idempotency-Key": "active"},
                )
            )
            assert await asyncio.to_thread(started.wait, 3)
            latest = (await client.get("/api/projects/demo/workflow-run")).json()
            assert latest["status"] == "running"
            assert (
                await client.post(
                    "/api/projects/demo/workflow-runs",
                    json=body,
                    headers={"Idempotency-Key": "duplicate"},
                )
            ).status_code == 409
            await client.post(
                f"/api/projects/demo/{cancel_route}/{latest['task_id']}/cancel"
            )
            release.set()
            await pending
            latest = (await client.get("/api/projects/demo/workflow-run")).json()
            assert latest["status"] == "cancelled", latest
            assert calls == []

    asyncio.run(run())


def test_restart_between_saved_stages_keeps_completed_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import minicut.workflows as module

    project(tmp_path)
    transcription = Transcriber()
    calls: list[HighlightBrief] = []
    configure = module.configure_outputs
    attempts: list[bool] = []

    def interrupted_configure(
        directory: Path, result: JsonObject, definition: JsonObject
    ) -> JsonObject:
        attempts.append(True)
        if len(attempts) == 1:
            raise ValueError("模拟配置阶段中断")
        return configure(directory, result, definition)

    monkeypatch.setattr(module, "configure_outputs", interrupted_configure)

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(
                app=create_app(
                    tmp_path, transcribe=transcription, highlights=generator(calls)
                )
            ),
            base_url="http://test",
        ) as client:
            saved = (
                await client.post(
                    "/api/workflows",
                    json=definition(layout={"subtitle_mode": "source"}),
                )
            ).json()
            task = (
                await client.post(
                    "/api/projects/demo/workflow-runs",
                    json={"asset_id": "asset", "workflow_id": saved["workflow_id"]},
                    headers={"Idempotency-Key": "restart"},
                )
            ).json()
            path = tmp_path / "demo/.minicut/jobs" / f"{task['task_id']}.json"
            interrupted = json.loads(path.read_text())
            assert interrupted["result"]["outputs"]
            interrupted.update(status="running", owner_pid=0)
            path.write_text(json.dumps(interrupted))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(
                app=create_app(
                    tmp_path, transcribe=transcription, highlights=generator(calls)
                )
            ),
            base_url="http://test",
        ) as restarted:
            current = (await restarted.get("/api/projects/demo/workflow-run")).json()
            assert current["status"] == "failed"
            assert current["resumable"]
            response = await restarted.post(
                f"/api/projects/demo/workflow-runs/{task['task_id']}/resume"
            )
            assert response.status_code == 202
            completed = (await restarted.get("/api/projects/demo/workflow-run")).json()
            assert completed["status"] == "succeeded", completed["error"]
            assert completed["result"]["outputs"][0]["subtitle_mode"] == "source"
            assert len(transcription.calls) == len(calls) == 1

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["register", "full", "submit"])
def test_workflow_admission_failure_can_resume_its_saved_definition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    project(tmp_path)
    transcription = Transcriber()
    calls: list[HighlightBrief] = []
    app = create_app(tmp_path, transcribe=transcription, highlights=generator(calls))

    def fail_register(
        self: BackgroundTasks,
        func: Callable[..., object],
        *args: object,
        **kwargs: object,
    ) -> NoReturn:
        raise RuntimeError("registration failed")

    def fail_submit(
        self: TaskWorkerPool, operations: list[Callable[[], None]]
    ) -> NoReturn:
        if failure == "full":
            raise TaskQueueFull("queue full")
        raise RuntimeError("submission failed")

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            saved = (await client.post("/api/workflows", json=definition())).json()
            body = {"asset_id": "asset", "workflow_id": saved["workflow_id"]}
            headers = {"Idempotency-Key": "admission"}
            with monkeypatch.context() as patch:
                if failure == "register":
                    patch.setattr(BackgroundTasks, "add_task", fail_register)
                else:
                    patch.setattr(TaskWorkerPool, "submit_many", fail_submit)
                rejected = await client.post(
                    "/api/projects/demo/workflow-runs", json=body, headers=headers
                )
                assert rejected.status_code == (503 if failure == "full" else 500)
            failed = (await client.get("/api/projects/demo/workflow-run")).json()
            assert failed["status"] == "failed" and failed["resumable"]
            assert len(transcription.calls) == len(calls) == 0
            repeated = await client.post(
                "/api/projects/demo/workflow-runs", json=body, headers=headers
            )
            assert repeated.json()["status"] == "failed"
            await client.delete(f"/api/workflows/{saved['workflow_id']}")
            resumed = await client.post(
                f"/api/projects/demo/workflow-runs/{failed['task_id']}/resume"
            )
            assert resumed.status_code == 202, resumed.text
            completed = (await client.get("/api/projects/demo/workflow-run")).json()
            assert completed["status"] == "succeeded", completed["error"]
            assert completed["task_id"] == failed["task_id"]
            assert len(transcription.calls) == len(calls) == 1

    asyncio.run(run())


def test_cancel_during_configuration_keeps_saved_stages_for_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import minicut.workflows as module

    project(tmp_path)
    transcription = Transcriber()
    calls: list[HighlightBrief] = []
    configured, release = Event(), Event()
    configure = module.configure_outputs
    attempts: list[bool] = []

    def pause_configure(
        directory: Path, result: JsonObject, definition: JsonObject
    ) -> JsonObject:
        attempts.append(True)
        saved = configure(directory, result, definition)
        configured.set()
        assert release.wait(5)
        return saved

    monkeypatch.setattr(module, "configure_outputs", pause_configure)
    app = create_app(tmp_path, transcribe=transcription, highlights=generator(calls))

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            saved = (await client.post("/api/workflows", json=definition())).json()
            pending = asyncio.create_task(
                client.post(
                    "/api/projects/demo/workflow-runs",
                    json={"asset_id": "asset", "workflow_id": saved["workflow_id"]},
                    headers={"Idempotency-Key": "configure"},
                )
            )
            try:
                assert await asyncio.to_thread(configured.wait, 3)
                cancelled = await client.post(
                    "/api/projects/demo/workflow-runs/workflow-run-configure/cancel"
                )
                assert cancelled.status_code == 200
                assert cancelled.json()["cancel_requested"]
            finally:
                release.set()
                await pending
            job = (await client.get("/api/projects/demo/workflow-run")).json()
            assert job["status"] == "cancelled" and job["cancel_requested"]
            assert job["configured"] and job["result"]["outputs"]
            assert job["child_task_ids"] == []
            resumed = await client.post(
                "/api/projects/demo/workflow-runs/workflow-run-configure/resume"
            )
            assert resumed.status_code == 202, resumed.text
            final = (await client.get("/api/projects/demo/workflow-run")).json()
            assert final["status"] == "succeeded", final["error"]
            assert not final["cancel_requested"]
            assert len(transcription.calls) == len(calls) == len(attempts) == 1

    asyncio.run(run())


def test_cancel_before_child_ids_are_saved_still_cancels_the_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project(tmp_path)
    admitted, track, child_cancelled, release = (Event() for _ in range(4))
    calls: list[HighlightBrief] = []
    schedule = TaskExecutor.schedule
    cancel = TaskExecutor.cancel

    def pause_tracking(
        executor: TaskExecutor,
        runners: list[TaskRunner],
        register: Callable[[list[TaskRunner]], None],
    ) -> None:
        schedule(executor, runners, register)
        if runners and runners[0].identity[1].endswith("-transcribe"):
            admitted.set()
            assert track.wait(5)

    def signal_cancel(
        executor: TaskExecutor, project: str, task: str
    ) -> dict[str, object]:
        job = cancel(executor, project, task)
        if task.endswith("-transcribe"):
            child_cancelled.set()
        return job

    class BlockingTranscriber(Transcriber):
        def execute(self, request: TranscribeRequest) -> TranscribeResult:
            assert release.wait(5)
            assert request.cancellation is not None
            request.cancellation.raise_if_cancelled()
            return super().execute(request)

    monkeypatch.setattr(TaskExecutor, "schedule", pause_tracking)
    monkeypatch.setattr(TaskExecutor, "cancel", signal_cancel)
    app = create_app(
        tmp_path, transcribe=BlockingTranscriber(), highlights=generator(calls)
    )

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            saved = (await client.post("/api/workflows", json=definition())).json()
            pending = asyncio.create_task(
                client.post(
                    "/api/projects/demo/workflow-runs",
                    json={"asset_id": "asset", "workflow_id": saved["workflow_id"]},
                    headers={"Idempotency-Key": "tracking"},
                )
            )
            try:
                assert await asyncio.to_thread(admitted.wait, 3)
                current = (await client.get("/api/projects/demo/workflow-run")).json()
                assert current["child_task_ids"] == []
                cancelled = await client.post(
                    "/api/projects/demo/workflow-runs/workflow-run-tracking/cancel"
                )
                assert cancelled.status_code == 200
                track.set()
                assert await asyncio.to_thread(child_cancelled.wait, 3)
            finally:
                track.set()
                release.set()
                await pending
            final = (await client.get("/api/projects/demo/workflow-run")).json()
            child = (
                await client.get(
                    "/api/projects/demo/tasks/workflow-run-tracking-transcribe"
                )
            ).json()
            assert final["status"] == child["status"] == "cancelled"
            assert calls == []

    asyncio.run(run())


def test_full_export_preset_applies_style_to_saved_workflow_output(
    tmp_path: Path,
) -> None:
    from dataclasses import asdict

    from minicut.export_settings import ExportSettings
    from minicut.subtitle_style import SubtitleStyle
    from minicut.workflows import configure_outputs

    directory = project(tmp_path)
    Transcriber().execute(
        TranscribeRequest(directory, directory / "source.mp4", "whisper", "tiny", "en")
    )
    result = generator([])(
        directory,
        "asset",
        "collection",
        HighlightTaskBody.model_validate(
            {"asset_id": "asset", **WorkflowBody.model_validate(definition()).brief()}
        ).brief(),
    )
    subtitles: JsonObject = {
        "subtitle_mode": "source",
        "subtitle_bottom_percent": 25,
        "subtitle_style": asdict(
            SubtitleStyle(
                source_size=90,
                translation_size=50,
                text_color="#ffcc00",
                background_enabled=True,
            )
        ),
    }
    body = WorkflowBody.model_validate(
        definition(
            export_options={"subtitle_mode": "burned", "subtitle_settings": subtitles}
        )
    )
    updated = configure_outputs(directory, result, body.model_dump())
    plan = (
        OutputCollectionRepository(directory, "collection")
        .read(source_segments(directory, "asset", "collection"))
        .plans[0]
    )
    assert updated["outputs"][0]["revision"] == plan.revision == 2
    assert plan.subtitle_style == SubtitleStyle.from_dict(subtitles["subtitle_style"])
    assert plan.subtitle_mode == "source" and plan.subtitle_bottom_percent == 25
    from minicut.export_settings import ExportDraft

    assert (
        ExportDraft.model_validate(
            ExportSettings(directory).read("single", "collection", "o")["draft"]
        ).options.subtitle_settings
        is None
    )
    configure_outputs(directory, updated, body.model_dump())
    assert (
        OutputCollectionRepository(directory, "collection")
        .read(source_segments(directory, "asset", "collection"))
        .plans[0]
        .revision
        == 2
    )
