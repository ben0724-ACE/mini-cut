import asyncio
import json
import os
import shutil
from pathlib import Path

import httpx
import pytest

from minicut.api import create_app


@pytest.mark.parametrize("keep_original", [True, False])
def test_copied_project_is_addressed_and_deleted_by_its_own_directory(
    tmp_path: Path, keep_original: bool
) -> None:
    async def run() -> None:
        root = tmp_path / "projects"
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(root)), base_url="http://test"
        ) as client:
            await client.post(
                "/api/projects", json={"project_id": "original", "name": "原项目"}
            )
            copied = root / "intro-review"
            shutil.copytree(root / "original", copied)
            manifest = json.loads((copied / "manifest.json").read_text())
            manifest["name"] = "导读功能验收（独立样片）"
            (copied / "manifest.json").write_text(json.dumps(manifest))
            if not keep_original:
                assert (await client.delete("/api/projects/original")).status_code == 200

            projects = (await client.get("/api/projects")).json()
            sample = next(p for p in projects if p["name"] == manifest["name"])
            assert sample["project_id"] == "intro-review"
            assert len({p["project_id"] for p in projects}) == len(projects)
            url = f"/api/projects/{sample['project_id']}"
            detail = await client.get(url)
            assert detail.status_code == 200
            assert detail.json()["project_id"] == sample["project_id"]
            assert detail.json()["name"] == manifest["name"]
            assert (await client.delete(url)).status_code == 200
            assert not copied.exists()
            remaining = (await client.get("/api/projects")).json()
            assert [p["project_id"] for p in remaining] == (
                ["original"] if keep_original else []
            )
            missing = await client.get(url)
            assert missing.status_code == 404
            assert missing.json()["detail"] == "项目已删除或不存在"
            if keep_original:
                assert (await client.get("/api/projects/original")).status_code == 200

    asyncio.run(run())


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
