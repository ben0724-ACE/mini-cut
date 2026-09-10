import asyncio
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx

from minicut.api import create_app


class ProjectApiTest(unittest.TestCase):
    def test_creates_lists_and_queries_projects_through_application_services(
        self,
    ) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            app = create_app(root)

            async def requests() -> tuple[
                httpx.Response, httpx.Response, httpx.Response
            ]:
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://test"
                ) as client:
                    return (
                        await client.post(
                            "/api/projects", json={"project_id": "demo-1"}
                        ),
                        await client.get("/api/projects"),
                        await client.get("/api/projects/demo-1"),
                    )

            created, listed, detail = asyncio.run(requests())

            self.assertEqual(created.status_code, 201)
            self.assertEqual(
                created.json(),
                {"project_id": "demo-1", "asset_count": 0, "asset_ids": []},
            )
            self.assertEqual(
                listed.json(), [{"project_id": "demo-1", "asset_count": 0}]
            )
            self.assertEqual(detail.json(), created.json())
            self.assertTrue((root / "demo-1/manifest.json").is_file())

    def test_rejects_invalid_ids_before_creating_a_project(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            app = create_app(root)

            async def request() -> httpx.Response:
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://test"
                ) as client:
                    return await client.post(
                        "/api/projects", json={"project_id": "../escape"}
                    )

            response = asyncio.run(request())

            self.assertEqual(response.status_code, 422)
            self.assertFalse((root.parent / "escape").exists())


if __name__ == "__main__":
    unittest.main()
