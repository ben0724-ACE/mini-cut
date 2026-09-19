import asyncio
import json
import os
from pathlib import Path

import httpx

from minicut.api import create_app


def test_delete_project_checks_jobs_and_preserves_external_files(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        root = tmp_path / "projects"
        external = tmp_path / "original.mp4"
        external.write_bytes(b"original")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(root)), base_url="http://test"
        ) as client:
            data = (await client.post("/api/projects", json={"name": "test"})).json()
            project_id = data["project_id"]
            directory = root / project_id
            jobs = directory / ".minicut/jobs"
            jobs.mkdir(parents=True)
            job = jobs / "active.json"
            job.write_text(json.dumps({"status": "running", "owner_pid": os.getpid()}))
            url = f"/api/projects/{project_id}"
            assert (await client.delete(url)).status_code == 409
            assert directory.exists()
            job.write_text(json.dumps({"status": "succeeded"}))
            (directory / "external-link").symlink_to(external)
            assert (await client.delete(url)).status_code == 200
            assert not directory.exists()
            assert external.read_bytes() == b"original"
            assert (await client.get("/api/projects")).json() == []
            assert (await client.delete(url)).status_code == 404
            (root / "linked").symlink_to(tmp_path, target_is_directory=True)
            assert (await client.delete("/api/projects/linked")).status_code == 400
            assert external.exists()

    asyncio.run(run())
