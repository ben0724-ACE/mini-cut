import asyncio
import wave
from pathlib import Path

import httpx

from minicut.api import create_app


def test_stream_import_rejects_bad_names_and_cleans_failed_media(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(tmp_path)),
            base_url="http://test",
        ) as client:
            await client.post("/api/projects", json={"project_id": "demo"})
            for name in ("../escape.mov", "a/b.mov", "a\\b.mov", "bad.txt"):
                result = await client.post(
                    "/api/projects/demo/assets",
                    params={"filename": name},
                    content=b"bad",
                )
                assert result.status_code == 400
            result = await client.post(
                "/api/projects/demo/assets",
                params={"filename": "测试.mov"},
                content=b"not media",
            )
            assert result.status_code == 400
            assert (await client.get("/api/projects/demo/assets")).json() == []
            assert not list((tmp_path / "demo/.minicut/media").glob("*/*"))

    asyncio.run(run())


def test_interrupted_stream_removes_partial_file(tmp_path: Path) -> None:
    async def interrupted():
        yield b"partial"
        raise RuntimeError("simulated disconnect")

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(tmp_path)),
            base_url="http://test",
        ) as client:
            await client.post("/api/projects", json={"project_id": "demo"})
            try:
                await client.post(
                    "/api/projects/demo/assets",
                    params={"filename": "partial.mov"},
                    content=interrupted(),
                )
            except RuntimeError:
                pass
            else:
                raise AssertionError("stream interruption was not exercised")
            assert not list((tmp_path / "demo/.minicut/media").iterdir())
            assert (await client.get("/api/projects/demo/assets")).json() == []

    asyncio.run(run())


def test_real_wav_stream_import_and_duplicate_cleanup(tmp_path: Path) -> None:
    source = tmp_path / "原音频.wav"
    with wave.open(str(source), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\x00\x00" * 8000)
    original = source.read_bytes()

    async def chunks():
        for offset in range(0, len(original), 1024):
            yield original[offset : offset + 1024]

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(tmp_path / "projects")),
            base_url="http://test",
        ) as client:
            await client.post("/api/projects", json={"project_id": "demo"})
            first = await client.post(
                "/api/projects/demo/assets",
                params={"filename": "原音频.wav"},
                content=chunks(),
            )
            assert first.status_code == 201
            second = await client.post(
                "/api/projects/demo/assets",
                params={"filename": "重复.wav"},
                content=chunks(),
            )
            assert second.json()["asset_id"] == first.json()["asset_id"]
            assets = (await client.get("/api/projects/demo/assets")).json()
            assert len(assets) == 1
            assert assets[0]["name"] == "原音频.wav"
            assert abs(assets[0]["duration_ms"] - 1000) < 20
            assert not assets[0]["has_transcript"]
            assert (
                len(list((tmp_path / "projects/demo/.minicut/media").glob("*/*"))) == 1
            )
            assert source.read_bytes() == original

    asyncio.run(run())
