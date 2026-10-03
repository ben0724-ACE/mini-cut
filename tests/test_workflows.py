"""Minimal mode reuses tasks, preserves snapshots and recovers without duplicate AI."""

import asyncio
import json
from threading import Event
from types import SimpleNamespace

import httpx
import pytest

from minicut.api import create_app
from minicut.errors import UserInputError
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
from minicut.transcript import Transcript, TranscriptSource, Word
from minicut.workflows import WorkflowBody, WorkflowLibrary
from tests.test_generation_presets import configuration


def definition(**changes):
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


def project(root):
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
    def __init__(self):
        self.calls = []

    def execute(self, request):
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
        return SimpleNamespace(
            transcript_id="t", asset_id="asset", word_count=1, reused=False
        )


def generator(calls, failures=0, empty=False):
    def generate(directory, asset, collection, brief):
        calls.append(brief)
        if len(calls) <= failures:
            raise UserInputError("模拟模型阶段失败")
        repo = OutputCollectionRepository(directory, collection)
        result = {
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


def test_workflow_library_snapshots_shared_presets_and_validates(tmp_path):
    library = WorkflowLibrary(tmp_path)
    assert library.list() == []
    assert not library.path.exists()
    body = WorkflowBody.model_validate(definition())
    saved = library.save(body)
    assert saved["generation"]["count"] == 2

    async def run():
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
def test_one_click_reuses_tasks_idempotency_and_applies_saved_settings(tmp_path, empty):
    project(tmp_path)
    transcription = Transcriber()
    calls = []
    app = create_app(
        tmp_path, transcribe=transcription, highlights=generator(calls, empty=empty)
    )

    async def run():
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
    tmp_path,
):
    project(tmp_path)
    transcription = Transcriber()
    calls = []

    async def run():
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


def test_cancel_and_mode_independent_duplicate_start(tmp_path):
    project(tmp_path)
    started = Event()
    release = Event()
    calls = []

    class BlockingTranscriber(Transcriber):
        def execute(self, request):
            started.set()
            release.wait(5)
            request.cancellation.raise_if_cancelled()
            return super().execute(request)

    async def run():
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
                f"/api/projects/demo/workflow-runs/{latest['task_id']}/cancel"
            )
            release.set()
            await pending
            latest = (await client.get("/api/projects/demo/workflow-run")).json()
            assert latest["status"] == "cancelled", latest
            assert calls == []

    asyncio.run(run())


def test_restart_between_saved_stages_keeps_completed_selection(tmp_path, monkeypatch):
    import minicut.workflows as module

    project(tmp_path)
    transcription = Transcriber()
    calls = []
    configure = module.configure_outputs
    attempts = []

    def interrupted_configure(*args):
        attempts.append(True)
        if len(attempts) == 1:
            raise ValueError("模拟配置阶段中断")
        return configure(*args)

    monkeypatch.setattr(module, "configure_outputs", interrupted_configure)

    async def run():
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
