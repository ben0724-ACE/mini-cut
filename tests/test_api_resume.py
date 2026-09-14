import asyncio
import json
from pathlib import Path

import httpx

from minicut.api import create_app
from minicut.application import TranscribeRequest, TranscribeResult
from minicut.project import ProjectManifest, ProjectRepository


def test_restart_marks_old_running_task_and_resumes_saved_request(
    tmp_path: Path,
) -> None:
    ProjectRepository(tmp_path / "demo").create(ProjectManifest("demo"))
    jobs = tmp_path / "demo/.minicut/jobs"
    jobs.mkdir(parents=True)
    (jobs / "old.json").write_text(
        json.dumps(
            {
                "task_id": "old",
                "kind": "transcribe",
                "status": "running",
                "request": {
                    "source_path": "/source.mov",
                    "provider": "mlx",
                    "model": "large-v3-turbo",
                    "language": "en",
                },
                "result": None,
                "error": None,
            }
        )
    )

    class Transcriber:
        def execute(self, request: TranscribeRequest) -> TranscribeResult:
            assert request.language == "en"
            assert request.cancellation is not None
            request.on_chunk_progress(1, 2)
            return TranscribeResult("transcript", "asset", 2, True)

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(
                app=create_app(tmp_path, transcribe=Transcriber())
            ),
            base_url="http://test",
        ) as client:
            old = (await client.get("/api/projects/demo/tasks/old")).json()
            assert old["status"] == "failed"
            assert old["resumable"] is True
            resumed = await client.post("/api/projects/demo/tasks/old/resume")
            assert resumed.status_code == 202
            repeated = await client.post("/api/projects/demo/tasks/old/resume")
            assert repeated.json()["task_id"] == resumed.json()["task_id"]
            current = (
                await client.get(
                    "/api/projects/demo/tasks/" + resumed.json()["task_id"]
                )
            ).json()
            assert current["status"] == "succeeded"
            assert current["result"]["reused"] is True
            assert (
                await client.post(
                    "/api/projects/demo/tasks/" + current["task_id"] + "/resume"
                )
            ).status_code == 409

    asyncio.run(run())
