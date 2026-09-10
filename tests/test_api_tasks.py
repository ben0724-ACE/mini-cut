import asyncio
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx

from minicut.api import create_app
from minicut.application import (
    PlanRequest,
    PlanResult,
    RenderRequest,
    RenderResult,
    TranscribeRequest,
    TranscribeResult,
)
from minicut.project import ProjectManifest, ProjectRepository


class FakeTranscribe:
    def __init__(self) -> None:
        self.requests: list[TranscribeRequest] = []

    def execute(self, request: TranscribeRequest) -> TranscribeResult:
        self.requests.append(request)
        return TranscribeResult("transcript-1", "asset-1", 47)


class FakePlan:
    def __init__(self) -> None:
        self.requests: list[PlanRequest] = []

    def execute(self, request: PlanRequest) -> PlanResult:
        self.requests.append(request)
        return PlanResult(
            request.asset_id,
            5,
            2,
            request.project_directory / ".minicut/plans/asset-1.json",
        )


class FakeRender:
    def __init__(self) -> None:
        self.requests: list[RenderRequest] = []

    def execute(self, request: RenderRequest) -> RenderResult:
        self.requests.append(request)
        return RenderResult(
            request.output_path,
            request.output_path.with_suffix(".srt"),
            11_380,
        )


class TaskApiTest(unittest.TestCase):
    def test_submits_all_task_kinds_and_persists_results(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            ProjectRepository(root / "demo").create(ProjectManifest("demo"))
            transcribe = FakeTranscribe()
            plan = FakePlan()
            render = FakeRender()
            app = create_app(
                root,
                transcribe=transcribe,
                plan=plan,
                render=render,
            )

            async def requests() -> tuple[
                httpx.Response, httpx.Response, httpx.Response
            ]:
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://test"
                ) as client:
                    transcribed = await client.post(
                        "/api/projects/demo/tasks/transcribe",
                        headers={"Idempotency-Key": "transcribe-1"},
                        json={
                            "source_path": "/media/input.mov",
                            "provider": "mlx",
                            "model": "large-v3-turbo",
                        },
                    )
                    planned = await client.post(
                        "/api/projects/demo/tasks/plan",
                        headers={"Idempotency-Key": "plan-1"},
                        json={"asset_id": "asset-1", "target_duration_ms": 10_000},
                    )
                    rendered = await client.post(
                        "/api/projects/demo/tasks/render",
                        headers={"Idempotency-Key": "render-1"},
                        json={"asset_id": "asset-1", "output_name": "result.mp4"},
                    )
                    self.assertEqual(transcribed.status_code, 202)
                    self.assertEqual(planned.status_code, 202)
                    self.assertEqual(rendered.status_code, 202)
                    return (
                        await client.get("/api/projects/demo/tasks/transcribe-1"),
                        await client.get("/api/projects/demo/tasks/plan-1"),
                        await client.get("/api/projects/demo/tasks/render-1"),
                    )

            transcribed, planned, rendered = asyncio.run(requests())

            self.assertEqual(transcribed.json()["result"]["word_count"], 47)
            self.assertEqual(planned.json()["result"]["kept_segments"], 5)
            self.assertEqual(rendered.json()["result"]["duration_ms"], 11_380)
            self.assertEqual(len(transcribe.requests), 1)
            self.assertEqual(len(plan.requests), 1)
            self.assertEqual(len(render.requests), 1)
            self.assertEqual(
                render.requests[0].output_path, root / "demo/exports/result.mp4"
            )

    def test_repeated_submission_runs_once_and_conflicting_reuse_is_rejected(
        self,
    ) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            ProjectRepository(root / "demo").create(ProjectManifest("demo"))
            transcribe = FakeTranscribe()
            app = create_app(root, transcribe=transcribe)

            async def requests() -> tuple[httpx.Response, httpx.Response]:
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://test"
                ) as client:
                    headers = {"Idempotency-Key": "same-key"}
                    body = {
                        "source_path": "/media/input.mov",
                        "provider": "mlx",
                        "model": "large-v3-turbo",
                    }
                    first = await client.post(
                        "/api/projects/demo/tasks/transcribe",
                        headers=headers,
                        json=body,
                    )
                    repeated = await client.post(
                        "/api/projects/demo/tasks/transcribe",
                        headers=headers,
                        json=body,
                    )
                    conflict = await client.post(
                        "/api/projects/demo/tasks/transcribe",
                        headers=headers,
                        json={**body, "language": "en"},
                    )
                    self.assertEqual(first.status_code, 202)
                    return repeated, conflict

            repeated, conflict = asyncio.run(requests())

            self.assertEqual(repeated.status_code, 202)
            self.assertEqual(repeated.json()["status"], "succeeded")
            self.assertEqual(conflict.status_code, 409)
            self.assertEqual(len(transcribe.requests), 1)


if __name__ == "__main__":
    unittest.main()
