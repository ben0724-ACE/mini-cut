import asyncio
from pathlib import Path

import httpx
import pytest

import minicut.api as module
from minicut.api import create_app
from minicut.export_settings import PreviewOptions
from minicut.project import ProjectManifest, ProjectRepository


def test_preview_recovery_matches_all_output_settings_and_legacy_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ProjectRepository(tmp_path / "demo").create(ProjectManifest("demo"))
    calls: list[PreviewOptions] = []

    def preview(*args: object) -> dict[str, object]:
        options = args[5]
        assert isinstance(options, PreviewOptions)
        calls.append(options)
        return {
            "output_id": "o",
            "revision": 1,
            "media_url": "/preview.mp4",
            "duration_ms": 1000,
            "preview_options": options.model_dump(),
            "render_engine_version": module.RENDER_ENGINE_VERSION,
        }

    monkeypatch.setattr(module, "preview_output", preview)

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(tmp_path)),
            base_url="http://test",
        ) as client:
            route = "/api/projects/demo/tasks/output-preview"
            recovery = "/api/projects/demo/highlights/c/outputs/o/preview-task"
            base = {"collection_id": "c", "output_id": "o", "revision": 1}
            vertical = PreviewOptions(
                aspect_ratio="9:16",
                resolution=720,
                fit="crop",
                crop_left=10,
                subtitle_mode="burned",
                audio_fade_ms=100,
                denoiser_id="afftdn",
            ).model_dump()
            square = {**vertical, "aspect_ratio": "1:1"}
            for identity, options in (("vertical", vertical), ("square", square)):
                response = await client.post(
                    route,
                    json={**base, **options},
                    headers={"Idempotency-Key": identity},
                )
                assert response.status_code == 202
            assert (
                await client.get(recovery, params={"revision": 1, **vertical})
            ).json()["task_id"] == "vertical"
            assert (
                await client.get(recovery, params={"revision": 1, **square})
            ).json()["task_id"] == "square"
            assert (await client.get(recovery, params={"revision": 1})).json() is None
            for key, value in {
                "subtitle_mode": "soft",
                "audio_fade_ms": 0,
                "denoiser_id": "none",
                "resolution": 1080,
                "fit": "pad",
                "crop_left": 11,
            }.items():
                assert (
                    await client.get(
                        recovery, params={"revision": 1, **vertical, key: value}
                    )
                ).json() is None
            assert calls[0].model_dump() == vertical
            assert (
                await client.post(
                    route, json=base, headers={"Idempotency-Key": "legacy"}
                )
            ).status_code == 202
            assert calls[-1] == PreviewOptions()
            assert (await client.get(recovery, params={"revision": 1})).json()[
                "task_id"
            ] == "legacy"
            assert (
                await client.post(
                    route,
                    json={**base, "crop_left": 60, "crop_right": 40},
                    headers={"Idempotency-Key": "invalid"},
                )
            ).status_code == 422
            assert (
                await client.get(recovery, params={"revision": 1, "resolution": 480})
            ).status_code == 422

    asyncio.run(run())
