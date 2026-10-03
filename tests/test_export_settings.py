import asyncio
import json
from pathlib import Path
from typing import cast

import httpx
import pytest

from minicut.api import create_app
from minicut.export_settings import ExportDraft, ExportOptions, ExportSettings
from minicut.project import ProjectManifest, ProjectRepository


def setup_projects(root: Path) -> None:
    for name in ("one", "two"):
        project = root / name
        ProjectRepository(project).create(ProjectManifest(name))
        directory = project / ".minicut/highlight-results"
        directory.mkdir(parents=True)
        for collection in ("c", "other"):
            (directory / f"{collection}.json").write_text(
                json.dumps(
                    {
                        "asset_id": "asset",
                        "outputs": [{"output_id": "a"}, {"output_id": "b"}],
                    }
                )
            )


def test_drafts_restore_per_output_and_mode_and_inherit_only_common_settings(
    tmp_path: Path,
) -> None:
    setup_projects(tmp_path)

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(tmp_path)),
            base_url="http://test",
        ) as client:
            base = "/api/projects/one/highlights/c"
            single = f"{base}/outputs/a/export-settings"
            batch = f"{base}/export-settings"
            assert (await client.get(single)).json()["source"] == "default"
            assert not (tmp_path / "one/.minicut/export-settings.sqlite3").exists()
            draft = ExportDraft(
                options=ExportOptions(
                    aspect_ratio="9:16",
                    resolution=720,
                    subtitle_mode="burned",
                    crop_left=10,
                )
            ).model_dump(mode="json")
            assert (await client.put(single, json=draft)).status_code == 200
            inherited = (await client.get(f"{base}/outputs/b/export-settings")).json()
            assert inherited["source"] == "project"
            assert inherited["draft"] == draft
            assert (await client.get(batch)).json()["source"] == "default"
            batch_draft = {**draft, "overrides": {"a": {"aspect_ratio": "1:1"}}}
            assert (await client.put(batch, json=batch_draft)).status_code == 200
            assert (await client.get(batch)).json()["draft"]["overrides"]["a"][
                "aspect_ratio"
            ] == "1:1"
            other = (
                await client.get("/api/projects/one/highlights/other/export-settings")
            ).json()
            assert other["source"] == "project"
            assert other["draft"]["options"] == draft["options"]
            assert other["draft"]["overrides"] == {}
            assert (
                await client.get("/api/projects/two/highlights/c/export-settings")
            ).json()["source"] == "default"
            assert (
                await client.get(f"{base}/outputs/missing/export-settings")
            ).status_code == 404
            assert (await client.put(single, json=batch_draft)).status_code == 422
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(tmp_path)),
            base_url="http://test",
        ) as restarted:
            assert (await restarted.get(single)).json()["draft"] == draft
            assert (await restarted.get(batch)).json()["draft"]["overrides"]["a"][
                "aspect_ratio"
            ] == "1:1"

    asyncio.run(run())


def test_presets_crud_conflicts_and_saved_drafts_are_independent(
    tmp_path: Path,
) -> None:
    setup_projects(tmp_path)

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(tmp_path)),
            base_url="http://test",
        ) as client:
            path = "/api/export-presets"
            assert (await client.get(path)).json() == []
            body = {
                "name": "  Shorts  ",
                "options": {
                    "aspect_ratio": "9:16",
                    "resolution": 720,
                    "subtitle_mode": "burned",
                    "audio_fade_ms": 150,
                    "denoiser_id": "afftdn",
                    "crop_left": 10,
                },
            }
            response = await client.post(path, json=body)
            assert response.status_code == 201
            preset = response.json()
            item = f"{path}/{preset['preset_id']}"
            assert preset["name"] == "Shorts"
            draft = {
                "options": preset["options"],
                "preset_id": preset["preset_id"],
                "preset_name": preset["name"],
            }
            for project in ("one", "two"):
                assert (
                    await client.put(
                        f"/api/projects/{project}/highlights/c/outputs/a/export-settings",
                        json=draft,
                    )
                ).status_code == 200
            assert (
                await client.post(path, json={**body, "name": "shorts"})
            ).status_code == 409
            assert (
                await client.post(path, json={**body, "name": "Other"})
            ).status_code == 201
            assert (await client.patch(item, json={"name": "Other"})).status_code == 409
            renamed = (await client.patch(item, json={"name": "竖屏"})).json()
            assert renamed["options"] == preset["options"]
            changed = (
                await client.put(
                    item, json={"name": "竖屏", "options": {"aspect_ratio": "1:1"}}
                )
            ).json()
            assert changed["options"]["aspect_ratio"] == "1:1"
            assert changed["created_at"] == preset["created_at"]
            invalid = await client.put(
                item,
                json={"name": "竖屏", "options": {"crop_left": 60, "crop_right": 40}},
            )
            assert invalid.status_code == 422
            assert (await client.get(path)).json()[1] == changed
            assert (await client.delete(item)).status_code == 200
            assert (await client.delete(item)).status_code == 404
            assert (await client.patch(item, json={"name": "恢复"})).status_code == 404
            assert (await client.put(item, json=body)).status_code == 404
            applied = (
                await client.get(
                    "/api/projects/two/highlights/c/outputs/a/export-settings"
                )
            ).json()["draft"]
            assert applied["options"] == preset["options"]
            assert applied["preset_name"] == "Shorts"
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(tmp_path)),
            base_url="http://test",
        ) as restarted:
            assert len((await restarted.get(path)).json()) == 1

    asyncio.run(run())


@pytest.mark.parametrize(
    "options",
    [
        {"resolution": 480},
        {"subtitle_mode": "translated"},
        {"audio_fade_ms": 501},
        {"crop_top": -1},
        {"crop_left": 50, "crop_right": 50},
        {"cover_version": 1},
    ],
)
def test_invalid_presets_and_drafts_do_not_replace_saved_configuration(
    tmp_path: Path, options: dict[str, object]
) -> None:
    setup_projects(tmp_path)
    store = ExportSettings(tmp_path / "one")
    original = ExportDraft(options=ExportOptions(aspect_ratio="16:9"))
    store.save("single", "c", "a", original)

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(tmp_path)),
            base_url="http://test",
        ) as client:
            assert (
                await client.post(
                    "/api/export-presets", json={"name": "Invalid", "options": options}
                )
            ).status_code == 422
            assert (
                await client.put(
                    "/api/projects/one/highlights/c/outputs/a/export-settings",
                    json={"options": options},
                )
            ).status_code == 422
            assert store.read("single", "c", "a")["draft"] == original.model_dump(
                mode="json"
            )

    asyncio.run(run())


def test_batch_source_survives_restart_and_new_collections_default_to_outputs(
    tmp_path: Path,
) -> None:
    setup_projects(tmp_path)
    store = ExportSettings(tmp_path / "one")
    uniform = ExportDraft(
        settings_source="uniform",
        options=ExportOptions(aspect_ratio="9:16", subtitle_mode="burned"),
    )
    store.save("batch", "c", "", uniform)
    restarted = ExportSettings(tmp_path / "one")
    assert restarted.read("batch", "c", "")["draft"] == uniform.model_dump(mode="json")
    inherited = restarted.read("batch", "other", "")["draft"]
    assert isinstance(inherited, dict)
    assert inherited["settings_source"] == "output"
    assert inherited["options"] == uniform.options.model_dump(mode="json")
    assert (
        ExportDraft.model_validate(
            {"options": uniform.options.model_dump()}
        ).settings_source
        == "output"
    )


def test_complete_subtitle_presets_restore_across_projects_and_restart(
    tmp_path: Path,
) -> None:
    from dataclasses import asdict

    from minicut.subtitle_style import SubtitleStyle

    setup_projects(tmp_path)
    layout: dict[str, object] = {
        "subtitle_mode": "translated",
        "subtitle_order": "translation_first",
        "subtitle_horizontal_percent": 55,
        "subtitle_bottom_percent": 20,
        "subtitle_source_scale": 1,
        "subtitle_translation_scale": 1,
        "subtitle_style": asdict(
            SubtitleStyle(
                source_font_id="heiti",
                translation_font_id="songti",
                source_size=88,
                translation_size=60,
                text_color="#ffcc00",
                stroke_color="#123456",
                stroke_width=6,
                shadow_color="#334455",
                shadow_width=3,
                bold=False,
                background_enabled=True,
                background_color="#112233",
                background_opacity=65,
            )
        ),
    }

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(tmp_path)),
            base_url="http://test",
        ) as client:
            saved = await client.post(
                "/api/export-presets",
                json={
                    "name": "Full",
                    "options": {"subtitle_mode": "burned", "subtitle_settings": layout},
                },
            )
            assert saved.status_code == 201
            preset = saved.json()
            assert preset["options"]["subtitle_settings"] == layout
            for project in ("one", "two"):
                route = f"/api/projects/{project}/highlights/c/export-settings"
                response = await client.put(
                    route,
                    json={"settings_source": "uniform", "options": preset["options"]},
                )
                assert response.status_code == 200
                assert (await client.get(route)).json()["draft"]["options"][
                    "subtitle_settings"
                ] == layout
            invalid = {
                **layout,
                "subtitle_style": {
                    **cast(dict[str, object], layout["subtitle_style"]),
                    "source_size": 0,
                },
            }
            assert (
                await client.put(
                    f"/api/export-presets/{preset['preset_id']}",
                    json={"name": "Full", "options": {"subtitle_settings": invalid}},
                )
            ).status_code == 422
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(tmp_path)),
            base_url="http://test",
        ) as restarted:
            assert (await restarted.get("/api/export-presets")).json() == [preset]
            assert (
                await restarted.get("/api/projects/two/highlights/c/export-settings")
            ).json()["draft"]["options"]["subtitle_settings"] == layout

    asyncio.run(run())
