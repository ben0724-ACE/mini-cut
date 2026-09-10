import asyncio
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx

from minicut.api import create_app
from minicut.media import MediaAsset
from minicut.project import ProjectRepository


class MediaApiTest(unittest.TestCase):
    def test_serves_registered_source_and_project_export_with_byte_ranges(
        self,
    ) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            app = create_app(root / "projects")
            source = root / "source.mp4"
            source.write_bytes(b"0123456789")

            async def requests() -> tuple[httpx.Response, httpx.Response]:
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://test"
                ) as client:
                    created = await client.post(
                        "/api/projects", json={"project_id": "demo"}
                    )
                    self.assertEqual(created.status_code, 201)
                    ProjectRepository(root / "projects/demo").add_asset(
                        MediaAsset("asset-1", str(source), 1000, (), "fingerprint")
                    )
                    export = root / "projects/demo/exports/result.srt"
                    export.parent.mkdir(parents=True)
                    export.write_bytes(b"subtitle")
                    return (
                        await client.get(
                            "/api/projects/demo/media/source/asset-1",
                            headers={"Range": "bytes=2-5"},
                        ),
                        await client.get("/api/projects/demo/media/exports/result.srt"),
                    )

            partial, complete = asyncio.run(requests())

            self.assertEqual(partial.status_code, 206)
            self.assertEqual(partial.content, b"2345")
            self.assertEqual(partial.headers["content-range"], "bytes 2-5/10")
            self.assertEqual(partial.headers["accept-ranges"], "bytes")
            self.assertEqual(complete.status_code, 200)
            self.assertEqual(complete.content, b"subtitle")
            self.assertEqual(complete.headers["content-length"], "8")

    def test_rejects_traversal_escaping_symlinks_and_invalid_ranges(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            app = create_app(root / "projects")
            secret = root / "secret.txt"
            secret.write_text("not public", encoding="utf-8")

            async def requests() -> tuple[
                httpx.Response, httpx.Response, httpx.Response
            ]:
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://test"
                ) as client:
                    await client.post("/api/projects", json={"project_id": "demo"})
                    exports = root / "projects/demo/exports"
                    exports.mkdir(parents=True)
                    media = exports / "result.mp4"
                    media.write_bytes(b"1234")
                    (exports / "escape.txt").symlink_to(secret)
                    return (
                        await client.get(
                            "/api/projects/demo/media/exports/%2E%2E%2F%2E%2E%2Fsecret.txt"
                        ),
                        await client.get("/api/projects/demo/media/exports/escape.txt"),
                        await client.get(
                            "/api/projects/demo/media/exports/result.mp4",
                            headers={"Range": "bytes=50-60"},
                        ),
                    )

            traversal, symlink, invalid_range = asyncio.run(requests())

            self.assertEqual(traversal.status_code, 400)
            self.assertEqual(symlink.status_code, 400)
            self.assertNotIn(b"not public", traversal.content + symlink.content)
            self.assertEqual(invalid_range.status_code, 416)
            self.assertEqual(invalid_range.headers["content-range"], "bytes */4")


if __name__ == "__main__":
    unittest.main()
