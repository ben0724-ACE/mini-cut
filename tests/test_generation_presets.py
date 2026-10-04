"""Cross-project templates stay independent of applied drafts and history."""

import asyncio
from pathlib import Path
from typing import cast

import httpx
import pytest

from minicut.api import create_app
from minicut.generation_settings import GenerationDraft
from minicut.highlight_brief import HighlightBrief, HighlightPreset
from minicut.media import MediaAsset
from minicut.project import ProjectManifest, ProjectRepository


def configuration() -> dict[str, object]:
    return GenerationDraft(
        preset=HighlightPreset.KNOWLEDGE,
        prompts={
            HighlightPreset.KNOWLEDGE: "完整的知识解释",
            HighlightPreset.OPINION: "无关草稿不应进入模板",
        },
        instructions="保留例子和限定条件",
        count=2,
        min_seconds=30,
        max_seconds=90,
        hook_enabled=True,
        hook_seconds=12.5,
        overlap_percent=20,
        body_mode="compact",
        translation_enabled=True,
        translation_language="en",
        subtitle_mode="translated",
    ).model_dump(mode="json")


def setup_projects(root: Path) -> None:
    for name in ("one", "two"):
        ProjectRepository(root / name).create(
            ProjectManifest(
                name,
                assets=(MediaAsset("asset", "/media/test.mov", 10000, (), "existing"),),
            )
        )
        transcript = root / name / ".minicut/transcripts/asset.json"
        transcript.parent.mkdir(parents=True)
        transcript.write_text("{}")


def test_library_is_shared_persistent_and_independent_of_project_deletion(
    tmp_path: Path,
) -> None:
    setup_projects(tmp_path)

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(tmp_path)),
            base_url="http://test",
        ) as client:
            assert (await client.get("/api/generation-presets")).json() == []
            assert not (tmp_path / ".minicut/generation-presets.sqlite3").exists()
            response = await client.post(
                "/api/generation-presets",
                json={"name": "  访谈短片  ", "draft": configuration()},
            )
            assert response.status_code == 201
            saved = response.json()
            assert saved["name"] == "访谈短片"
            assert saved["draft"]["prompts"] == {
                "knowledge_digest": "完整的知识解释\n\n保留例子和限定条件"
            }
            assert saved["draft"]["hook_seconds"] == 12.5
            # Applying the template makes an independent project draft.
            for project in ("one", "two"):
                applied = {
                    **configuration(),
                    "custom_preset_id": saved["preset_id"],
                    "custom_preset_name": saved["name"],
                    "custom_prompt": "已应用的文字",
                }
                assert (
                    await client.put(
                        f"/api/projects/{project}/assets/asset/generation-draft",
                        json=applied,
                    )
                ).status_code == 200
            assert (await client.delete("/api/projects/one")).status_code == 200
            assert (await client.get("/api/generation-presets")).json() == [saved]
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(tmp_path)),
            base_url="http://test",
        ) as restarted:
            assert (await restarted.get("/api/generation-presets")).json() == [saved]
            assert (
                await restarted.get("/api/projects/two/assets/asset/generation-draft")
            ).json()["draft"]["custom_prompt"] == "已应用的文字"
        # A different projects directory has its own local library.
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(tmp_path / "separate")),
            base_url="http://test",
        ) as separate:
            assert (await separate.get("/api/generation-presets")).json() == []

    asyncio.run(run())


def test_create_rename_update_validate_without_partial_changes(tmp_path: Path) -> None:
    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(tmp_path)),
            base_url="http://test",
        ) as client:
            path = "/api/generation-presets"
            first = (
                await client.post(
                    path, json={"name": "Interview", "draft": configuration()}
                )
            ).json()
            second = (
                await client.post(
                    path, json={"name": "Other", "draft": configuration()}
                )
            ).json()
            item = f"{path}/{first['preset_id']}"
            assert (
                await client.post(
                    path, json={"name": " interview ", "draft": configuration()}
                )
            ).status_code == 409
            assert (await client.patch(item, json={"name": "Other"})).status_code == 409
            assert (
                await client.post(path, json={"name": "   ", "draft": configuration()})
            ).status_code == 422
            renamed = (await client.patch(item, json={"name": "Renamed"})).json()
            assert renamed["draft"] == first["draft"]
            assert renamed["created_at"] == first["created_at"]
            invalid = {**configuration(), "count": 0}
            assert (
                await client.put(item, json={"name": "No", "draft": invalid})
            ).status_code == 422
            empty_prompt = {
                **configuration(),
                "prompts": {"knowledge_digest": " "},
                "instructions": "",
            }
            assert (
                await client.post(path, json={"name": "Empty", "draft": empty_prompt})
            ).status_code == 422
            updated = {
                **configuration(),
                "count": 4,
                "custom_preset_id": first["preset_id"],
                "custom_preset_name": "旧名字",
                "custom_prompt": "修改后的活动提示词",
            }
            latest = (
                await client.put(item, json={"name": "Renamed", "draft": updated})
            ).json()
            assert latest["draft"]["prompts"] == {
                "knowledge_digest": "修改后的活动提示词\n\n保留例子和限定条件"
            }
            assert latest["draft"]["custom_preset_id"] is None
            assert latest["draft"]["custom_prompt"] is None
            assert latest["draft"]["count"] == 4
            assert latest["created_at"] == first["created_at"]
            assert (
                await client.put(item, json={"name": "Other", "draft": configuration()})
            ).status_code == 409
            entries = (await client.get(path)).json()
            assert (
                next(
                    entry
                    for entry in entries
                    if entry["preset_id"] == first["preset_id"]
                )
                == latest
            )
            assert (
                next(
                    entry
                    for entry in entries
                    if entry["preset_id"] == second["preset_id"]
                )
                == second
            )
            assert (
                await client.patch(item, json={"name": "X", "draft": configuration()})
            ).status_code == 422
            assert (await client.delete(item)).status_code == 200
            assert (await client.delete(item)).status_code == 404
            assert (await client.patch(item, json={"name": "Again"})).status_code == 404
            assert (
                await client.put(item, json={"name": "Again", "draft": configuration()})
            ).status_code == 404
            assert (await client.get(path)).json() == [second]

    asyncio.run(run())


def test_template_changes_never_rewrite_applied_drafts_or_generation_history(
    tmp_path: Path,
) -> None:
    setup_projects(tmp_path)
    calls: list[HighlightBrief] = []

    def generate(
        project: Path, asset: str, collection: str, brief: HighlightBrief
    ) -> dict[str, object]:
        calls.append(brief)
        return {
            "collection_id": collection,
            "asset_id": asset,
            "brief": brief.to_dict(),
            "outputs": [],
        }

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(
                app=create_app(tmp_path, highlights=generate)
            ),
            base_url="http://test",
        ) as client:
            created = (
                await client.post(
                    "/api/generation-presets",
                    json={"name": "原始名字", "draft": configuration()},
                )
            ).json()
            identity = created["preset_id"]
            applied = {
                **configuration(),
                "custom_preset_id": identity,
                "custom_preset_name": "原始名字",
                "custom_prompt": "实际编辑的提示词",
            }
            draft_path = "/api/projects/two/assets/asset/generation-draft"
            await client.put(draft_path, json=applied)
            request = {
                "asset_id": "asset",
                "preset": "knowledge_digest",
                "count": 2,
                "preset_prompt": "实际编辑的提示词",
                "instructions": "本次要求",
                "custom_preset_id": identity,
                "custom_preset_name": "原始名字",
            }
            response = await client.post(
                "/api/projects/two/tasks/highlights",
                json=request,
                headers={"Idempotency-Key": "before"},
            )
            assert response.status_code == 202
            old = (await client.get("/api/projects/two/generation-history")).json()[0]
            assert old["custom_preset_name"] == "原始名字"
            assert old["brief"]["preset_prompt"] == "实际编辑的提示词"
            assert "custom_preset_name" not in calls[0].to_dict()
            assert "custom_preset_id" not in calls[0].to_dict()
            await client.patch(
                f"/api/generation-presets/{identity}", json={"name": "新名字"}
            )
            await client.put(
                f"/api/generation-presets/{identity}",
                json={"name": "新名字", "draft": configuration()},
            )
            await client.delete(f"/api/generation-presets/{identity}")
            assert (await client.get(draft_path)).json()["draft"] == applied
            assert (
                await client.get("/api/projects/two/generation-history")
            ).json() == [old]
            assert (
                await client.post(
                    "/api/projects/two/tasks/highlights",
                    json=request,
                    headers={"Idempotency-Key": "after"},
                )
            ).status_code == 202
            assert calls[-1].preset_prompt == "实际编辑的提示词"
            assert (
                await client.get("/api/projects/one/generation-history")
            ).json() == []

    asyncio.run(run())


@pytest.mark.parametrize(
    ("preset", "versions"),
    [
        ("podcast_highlights", {}),
        ("podcast_highlights", {"boundary_version": 2}),
        ("clean_speech", {}),
        ("clean_speech", {"cleanup_version": 1}),
        ("clean_speech", {"cleanup_version": 2}),
    ],
)
def test_legacy_builtin_request_still_matches_existing_idempotency_record(
    tmp_path: Path, preset: str, versions: dict[str, int],
) -> None:
    import json

    setup_projects(tmp_path)
    request: dict[str, object] = {
        "asset_id": "asset",
        "preset": preset,
        "count": 3,
        "min_ms": None,
        "max_ms": None,
        "hook_ms": None,
        "instructions": "",
        "preset_prompt": None,
        "max_source_overlap": 0.3,
        "body_mode": "continuous",
        "translation_language": None,
        "subtitle_mode": "bilingual",
        **versions,
    }
    job: dict[str, object] = {
        "task_id": "old",
        "kind": "highlights",
        "status": "failed",
        "request": request,
        "result": None,
        "error": "旧任务",
    }
    directory = tmp_path / "one/.minicut/jobs"
    directory.mkdir()
    (directory / "old.json").write_text(json.dumps(job))

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(tmp_path)),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/projects/one/tasks/highlights",
                json={key: value for key, value in request.items() if key not in versions},
                headers={"Idempotency-Key": "old"},
            )
            assert response.status_code == 202
            assert response.json()["error"] == "旧任务"
            history = cast(
                list[dict[str, object]],
                (await client.get("/api/projects/one/generation-history")).json(),
            )
            assert len(history) == 1
            assert history[0]["custom_preset_name"] is None
            changed = await client.post(
                "/api/projects/one/tasks/highlights",
                json={**request, "instructions": "新的要求"},
                headers={"Idempotency-Key": "old"},
            )
            assert changed.status_code == 409
            if preset == "podcast_highlights":
                changed_version = await client.post(
                    "/api/projects/one/tasks/highlights",
                    json={**request, "boundary_version": 3},
                    headers={"Idempotency-Key": "old"},
                )
                assert changed_version.status_code == 409
            assert json.loads((directory / "old.json").read_text()) == job

    asyncio.run(run())
