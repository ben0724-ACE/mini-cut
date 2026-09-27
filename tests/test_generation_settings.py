"""Persistence and submitted-history behavior through the local API."""

import asyncio
import json
from pathlib import Path

import httpx

from minicut.api import create_app
from minicut.errors import UserInputError
from minicut.generation_settings import GenerationDraft
from minicut.highlight_brief import HighlightBrief, HighlightPreset
from minicut.media import MediaAsset
from minicut.output_repository import OutputCollectionRepository
from minicut.project import ProjectManifest, ProjectRepository
from minicut.transcription_task import TranscriptionCancelled


def setup_project(root: Path, name: str = "demo") -> None:
    ProjectRepository(root / name).create(
        ProjectManifest(
            name,
            assets=tuple(
                MediaAsset(asset, f"/media/{asset}.mov", 10000, (), "existing")
                for asset in ("one", "two")
            ),
        )
    )
    for asset in ("one", "two"):
        path = root / name / ".minicut/transcripts" / f"{asset}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}")


def draft(prompt: str) -> dict[str, object]:
    return GenerationDraft(
        preset=HighlightPreset.PODCAST,
        prompts={
            HighlightPreset.PODCAST: prompt,
            HighlightPreset.OPINION: "未使用的预设草稿",
        },
        instructions="保留反方论述",
        count=0,
        min_seconds=100,
        max_seconds=90,
        hook_enabled=False,
        hook_seconds=12.5,
        overlap_percent=30,
        body_mode="compact",
        translation_enabled=False,
        translation_language="en",
        subtitle_mode="translated",
    ).model_dump(mode="json")


def test_drafts_survive_restart_and_remain_asset_and_project_specific(
    tmp_path: Path,
) -> None:
    setup_project(tmp_path)
    setup_project(tmp_path, "other")

    async def run() -> None:
        path = "/api/projects/demo/assets/one/generation-draft"
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(tmp_path)),
            base_url="http://test",
        ) as client:
            assert (await client.get(path)).json() == {
                "source": "default",
                "draft": None,
            }
            assert not (tmp_path / "demo/.minicut/generation-drafts.sqlite3").exists()
            # Incomplete text and invalid generation numbers are legitimate drafts.
            assert (await client.put(path, json=draft(""))).status_code == 200
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(tmp_path)),
            base_url="http://test",
        ) as client:
            own = (await client.get(path)).json()
            assert own["source"] == "asset"
            assert own["draft"] == draft("")
            assert own["updated_at"]
            second = path.replace("/one/", "/two/")
            assert (await client.get(second)).json()["source"] == "project"
            await client.put(second, json=draft("第二个素材"))
            assert (await client.get(second)).json()["draft"] == draft("第二个素材")
            assert (await client.get(path)).json()["draft"] == draft("")
            assert (await client.get(path.replace("/demo/", "/other/"))).json()[
                "source"
            ] == "default"
            assert (
                await client.put(path.replace("/one/", "/missing/"), json=draft(""))
            ).status_code == 404
            assert (
                await client.put(
                    path,
                    json={**draft(""), "prompts": {"podcast_highlights": "x" * 25001}},
                )
            ).status_code == 422
            assert (await client.get(path)).json()["draft"] == draft("")

    asyncio.run(run())


def test_history_snapshots_include_failures_cancellation_and_resolved_defaults(
    tmp_path: Path,
) -> None:
    setup_project(tmp_path)
    calls: list[HighlightBrief] = []

    def generate(
        project: Path, asset: str, collection: str, brief: HighlightBrief
    ) -> dict[str, object]:
        calls.append(brief)
        if brief.instructions == "失败":
            raise UserInputError("额度不足")
        if brief.instructions == "取消":
            raise TranscriptionCancelled()
        return {"collection_id": collection, "asset_id": asset, "outputs": []}

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(
                app=create_app(tmp_path, highlights=generate)
            ),
            base_url="http://test",
        ) as client:
            body = {"asset_id": "one", "preset": "podcast_highlights", "count": 2}
            for key, instructions in (
                ("ok", "完整论述"),
                ("bad", "失败"),
                ("cancel", "取消"),
            ):
                response = await client.post(
                    "/api/projects/demo/tasks/highlights",
                    json={**body, "instructions": instructions},
                    headers={"Idempotency-Key": key},
                )
                assert response.status_code == 202
            history_path = "/api/projects/demo/generation-history?asset_id=one"
            entries = (await client.get(history_path)).json()
            by_id = {entry["history_id"]: entry for entry in entries}
            assert by_id["ok"]["status"] == "succeeded"
            assert by_id["bad"]["status"] == "failed"
            assert by_id["bad"]["error"] == "额度不足"
            assert by_id["cancel"]["status"] == "cancelled"
            assert all(
                entry["created_at"] and not entry["missing_fields"] for entry in entries
            )
            assert by_id["ok"]["brief"] == calls[0].to_dict()
            assert calls[0].preset_prompt
            assert (await client.get(history_path.replace("one", "two"))).json() == []
            assert (
                len((await client.get("/api/projects/demo/generation-history")).json())
                == 3
            )
            # Saving a later draft never rewrites any submitted configuration.
            await client.put(
                "/api/projects/demo/assets/one/generation-draft",
                json=draft("完全不同的草稿"),
            )
            assert (await client.get(history_path)).json() == entries
            # Repeated submission with the same idempotency key stays one history item.
            await client.post(
                "/api/projects/demo/tasks/highlights",
                json={**body, "instructions": "完整论述"},
                headers={"Idempotency-Key": "ok"},
            )
            assert len((await client.get(history_path)).json()) == 3
            assert len(calls) == 3

    asyncio.run(run())


def test_unified_prompt_snapshot_survives_resume_without_filling_a_builtin(
    tmp_path: Path,
) -> None:
    setup_project(tmp_path)
    calls: list[HighlightBrief] = []

    def generate(
        project: Path, asset: str, collection: str, brief: HighlightBrief
    ) -> dict[str, object]:
        calls.append(brief)
        if len(calls) == 1:
            raise UserInputError("模拟可恢复失败")
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
            body = {
                "asset_id": "one",
                "preset": "podcast_highlights",
                "count": 2,
                "editing_prompt": "完整选材方向\n\n保留反方论述",
                "custom_preset_name": "我的流程",
            }
            task_path = "/api/projects/demo/tasks/highlights"
            assert (
                await client.post(
                    task_path,
                    json={**body, "instructions": "额外旧字段"},
                    headers={"Idempotency-Key": "ambiguous"},
                )
            ).status_code == 422
            assert (
                await client.post(
                    task_path, json=body, headers={"Idempotency-Key": "unified"}
                )
            ).status_code == 202
            history_path = "/api/projects/demo/generation-history"
            old = (await client.get(history_path)).json()[0]
            assert old["status"] == "failed" and not old["missing_fields"]
            assert old["brief"]["editing_prompt"] == body["editing_prompt"]
            assert (
                "preset_prompt" not in old["brief"]
                and "instructions" not in old["brief"]
            )
            assert old["custom_preset_name"] == "我的流程"
            await client.put(
                "/api/projects/demo/assets/one/generation-draft",
                json=draft("完全不同的草稿"),
            )
            response = await client.post("/api/projects/demo/tasks/unified/resume")
            assert response.status_code == 202
            assert calls[0].to_dict() == calls[1].to_dict() == old["brief"]
            entries = (await client.get(history_path)).json()
            assert (
                next(entry for entry in entries if entry["history_id"] == "unified")
                == old
            )

    asyncio.run(run())


def test_legacy_history_uses_recorded_text_without_filling_unknown_fields(
    tmp_path: Path,
) -> None:
    setup_project(tmp_path)
    directory = tmp_path / "demo"
    legacy: dict[str, object] = {
        "collection_id": "old",
        "asset_id": "one",
        "brief": {"preset": "opinion_first", "instructions": "旧要求", "count": 1},
        "outputs": [],
        "notes": [],
    }
    OutputCollectionRepository(directory, "old").write_highlight_result(legacy)
    jobs = directory / ".minicut/jobs"
    jobs.mkdir()
    job: dict[str, object] = {
        "task_id": "old-job",
        "kind": "highlights",
        "status": "succeeded",
        "request": {"asset_id": "one", "preset": "opinion_first"},
        "result": legacy,
    }
    (jobs / "old-job.json").write_text(json.dumps(job))
    orphan: dict[str, object] = {
        **legacy,
        "collection_id": "orphan",
        "asset_id": "two",
        "brief": {
            "preset_prompt": "实际保存的自定义原文",
            "preset": "knowledge_digest",
        },
    }
    OutputCollectionRepository(directory, "orphan").write_highlight_result(orphan)

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(tmp_path)),
            base_url="http://test",
        ) as client:
            entries = (await client.get("/api/projects/demo/generation-history")).json()
            assert len(entries) == 2  # A job and its result are one entry.
            old = next(entry for entry in entries if entry["history_id"] == "old-job")
            assert old["created_at"] is None
            assert old["brief"] == legacy["brief"]
            assert "preset_prompt" in old["missing_fields"]
            restored = (
                await client.get("/api/projects/demo/assets/one/generation-draft")
            ).json()
            assert restored["source"] == "history"
            assert restored["history"]["brief"] == legacy["brief"]
            assert restored["draft"] is None
            assert (
                next(entry for entry in entries if entry["history_id"] == "orphan")[
                    "brief"
                ]["preset_prompt"]
                == "实际保存的自定义原文"
            )
        assert json.loads((jobs / "old-job.json").read_text()) == job
        assert (
            json.loads((directory / ".minicut/highlight-results/old.json").read_text())
            == legacy
        )

    asyncio.run(run())


def test_resume_uses_submitted_snapshot_instead_of_current_default(
    tmp_path: Path,
) -> None:
    setup_project(tmp_path)
    calls: list[HighlightBrief] = []

    def generate(
        project: Path, asset: str, collection: str, brief: HighlightBrief
    ) -> dict[str, object]:
        calls.append(brief)
        if len(calls) == 1:
            raise UserInputError("暂时失败")
        return {"collection_id": collection, "asset_id": asset, "outputs": []}

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(
                app=create_app(tmp_path, highlights=generate)
            ),
            base_url="http://test",
        ) as client:
            await client.post(
                "/api/projects/demo/tasks/highlights",
                json={"asset_id": "one", "preset": "podcast_highlights", "count": 1},
                headers={"Idempotency-Key": "first"},
            )
            # Model a recorded snapshot whose template has since changed.
            path = tmp_path / "demo/.minicut/jobs/first.json"
            job = json.loads(path.read_text())
            job["generation_config"]["preset_prompt"] = "提交当时使用的原始模板"
            path.write_text(json.dumps(job))
            response = await client.post("/api/projects/demo/tasks/first/resume")
            assert response.status_code == 202
            assert calls[-1].preset_prompt == "提交当时使用的原始模板"
            history = (await client.get("/api/projects/demo/generation-history")).json()
            assert len(history) == 2
            assert history[0]["history_id"] == response.json()["task_id"]
            assert all(
                entry["brief"]["preset_prompt"] == "提交当时使用的原始模板"
                for entry in history
            )

    asyncio.run(run())
