import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx

from minicut.api import create_app
from minicut.project import ProjectRepository


def test_named_creation_generates_internal_id_and_persists_display_name() -> None:
    async def run(root: Path) -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(root)), base_url="http://test"
        ) as client:
            created = await client.post("/api/projects", json={"name": "我的播客"})
            assert created.status_code == 201
            data = created.json()
            assert data["name"] == "我的播客"
            assert data["project_id"] != "我的播客"
            assert (
                ProjectRepository(root / data["project_id"]).read().name == "我的播客"
            )
            assert (await client.get("/api/projects")).json()[0]["name"] == "我的播客"
            assert (await client.get(f"/api/projects/{data['project_id']}")).json()[
                "name"
            ] == "我的播客"
            assert (
                await client.post("/api/projects", json={"name": " "})
            ).status_code == 422

    with TemporaryDirectory() as directory:
        asyncio.run(run(Path(directory)))
