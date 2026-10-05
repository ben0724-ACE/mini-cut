import asyncio
import wave
from pathlib import Path
from threading import Barrier, Event, Lock

import httpx
import pytest

from minicut.api import create_app
from minicut.media import MediaAsset
from minicut.project import ProjectManifest, ProjectRepository


@pytest.mark.parametrize("duplicate", [False, True])
def test_concurrent_real_wav_uploads_preserve_successful_imports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, duplicate: bool
) -> None:
    sources: list[bytes] = []
    for index in range(2):
        source = tmp_path / f"source-{index}.wav"
        with wave.open(str(source), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(8000)
            sample = b"\x00\x00" if duplicate or index == 0 else b"\x01\x00"
            audio.writeframes(sample * 8000)
        sources.append(source.read_bytes())

    registrations = Barrier(2)
    writes_lock = Lock()
    second_written = Event()
    writes = 0
    add_asset = ProjectRepository.add_asset
    write = ProjectRepository._write  # pyright: ignore[reportPrivateUsage]

    def synchronized_add(
        repository: ProjectRepository, asset: MediaAsset
    ) -> MediaAsset:
        registrations.wait(timeout=5)
        return add_asset(repository, asset)

    def overlapping_write(
        repository: ProjectRepository, manifest: ProjectManifest
    ) -> None:
        nonlocal writes
        with writes_lock:
            writes += 1
            first_write = writes == 1
        if first_write:
            # Without serialization, the second upload publishes first and is lost
            # when this older snapshot replaces it. With a lock it must wait.
            second_written.wait(timeout=0.2)
        write(repository, manifest)
        if not first_write:
            second_written.set()

    async def run() -> None:
        root = tmp_path / "projects"
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(root)),
            base_url="http://test",
        ) as client:
            created = await client.post(
                "/api/projects", json={"project_id": "demo", "name": "并发导入"}
            )
            assert created.status_code == 201
            monkeypatch.setattr(ProjectRepository, "add_asset", synchronized_add)
            monkeypatch.setattr(ProjectRepository, "_write", overlapping_write)
            responses = await asyncio.gather(
                *(
                    client.post(
                        "/api/projects/demo/assets",
                        params={"filename": f"upload-{index}.wav"},
                        content=source,
                    )
                    for index, source in enumerate(sources)
                )
            )
            assert [response.status_code for response in responses] == [201, 201]
            returned_ids = {response.json()["asset_id"] for response in responses}
            expected_count = 1 if duplicate else 2
            assert len(returned_ids) == expected_count
            assets = (await client.get("/api/projects/demo/assets")).json()
            assert {asset["asset_id"] for asset in assets} == returned_ids
            manifest = ProjectRepository(root / "demo").read()
            assert manifest.name == "并发导入"
            assert len(manifest.assets) == expected_count
            assert all(Path(asset.source_path).is_file() for asset in manifest.assets)
            assert (
                len(list((root / "demo/.minicut/media").glob("*/*"))) == expected_count
            )
            for asset_id in returned_ids:
                assert (
                    await client.get(f"/api/projects/demo/media/source/{asset_id}")
                ).status_code == 200

    asyncio.run(run())


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
