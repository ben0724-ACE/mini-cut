"""One minimal-mode action produces actual video, subtitles and source audio."""

import asyncio
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import httpx
import pytest

from minicut.api import create_app
from minicut.application import TranscribeRequest, TranscribeResult
from minicut.cover_design import CoverDesign, CoverStore, design_directory
from minicut.cover_templates import CoverTemplateLibrary
from minicut.highlight_brief import HighlightBrief
from minicut.highlight_service import read_highlights, source_segments
from minicut.media import StreamType
from minicut.output_repository import OutputCollectionRepository
from minicut.probe import probe_media
from minicut.render_profile import source_dimensions
from tests.test_cover_design import cover_project as cover_project
from tests.test_workflows import definition


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required")
def test_automatic_export_and_recovery_do_not_repeat_selection(
    cover_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import minicut.api as api_module

    project = cover_project
    calls: list[HighlightBrief] = []

    class CachedTranscriber:
        def execute(self, request: TranscribeRequest) -> TranscribeResult:
            return TranscribeResult(
                transcript_id="t", asset_id="asset", word_count=1, reused=True
            )

    def generate(
        directory: Path, asset: str, collection: str, brief: HighlightBrief
    ) -> dict[str, object]:
        calls.append(brief)
        segments = source_segments(directory, asset)
        source = OutputCollectionRepository(directory, "collection").read(segments)
        repo = OutputCollectionRepository(directory, collection)
        repo.write(replace(source, collection_id=collection), segments)
        repo.write_highlight_result(
            {
                "collection_id": collection,
                "asset_id": asset,
                "brief": brief.to_dict(),
                "notes": [],
                "outputs": [{"output_id": "o", "reason": "测试"}],
            }
        )
        return read_highlights(directory, collection)

    real_export = api_module.export_output
    attempts: list[bool] = []

    def flaky_export(*args: Any, **kwargs: Any) -> dict[str, object]:
        attempts.append(True)
        if len(attempts) == 1:
            raise ValueError("模拟一次导出失败")
        return real_export(*args, **kwargs)

    monkeypatch.setattr(api_module, "export_output", flaky_export)

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(
                app=create_app(
                    project.parent, transcribe=CachedTranscriber(), highlights=generate
                )
            ),
            base_url="http://test",
        ) as client:
            saved = (
                await client.post(
                    "/api/workflows",
                    json=definition(
                        auto_export=True,
                        layout={},
                        export_options={"crop_left": 50, "subtitle_mode": "soft"},
                    ),
                )
            ).json()
            submitted = await client.post(
                "/api/projects/demo/workflow-runs",
                json={"asset_id": "asset", "workflow_id": saved["workflow_id"]},
                headers={"Idempotency-Key": "real"},
            )
            assert submitted.status_code == 202, submitted.text
            latest = (await client.get("/api/projects/demo/workflow-run")).json()
            assert latest["status"] == "failed", latest
            assert latest["configured"] is True
            await client.delete(f"/api/workflows/{saved['workflow_id']}")
            assert (
                await client.post(
                    f"/api/projects/demo/workflow-runs/{latest['task_id']}/resume"
                )
            ).status_code == 202
            completed = (await client.get("/api/projects/demo/workflow-run")).json()
            assert completed["status"] == "succeeded", completed["error"]
            assert len(calls) == 1
            assert len(completed["exports"]) == 1
            task = (
                await client.get(
                    f"/api/projects/demo/tasks/{completed['exports'][0]['taskId']}"
                )
            ).json()
            media = task["result"]
            video = (
                project
                / "exports"
                / unquote(media["media_url"].split("/media/exports/")[1])
            )
            assert source_dimensions(video) == (80, 120)
            assert any(
                stream.stream_type is StreamType.AUDIO
                for stream in probe_media(video).streams
            )
            subtitles = subprocess.check_output(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-i",
                    str(video),
                    "-map",
                    "0:s:0",
                    "-f",
                    "srt",
                    "-",
                ],
                text=True,
            )
            assert "设计封面" in subtitles.replace("\n", "")
            assert (await client.get(media["cover_url"])).status_code == 200
            assert (await client.get(media["subtitle_url"])).status_code == 200

    asyncio.run(run())


def test_workflow_owns_cover_background_after_template_deletion(
    cover_project: Path,
) -> None:
    from PIL import Image

    from minicut.workflows import WorkflowBody, WorkflowLibrary, configure_outputs

    project = cover_project
    directory = design_directory(project, "collection", "o")
    directory.mkdir(parents=True, exist_ok=True)
    image_id = "a" * 32
    Image.new("RGB", (100, 100), "green").save(directory / f"{image_id}.png")
    templates = CoverTemplateLibrary(project.parent)
    template = templates.save(
        "绿色封面",
        CoverDesign(mode="design", background_image=image_id, title="Original"),
        directory,
    )
    library = WorkflowLibrary(project.parent)
    saved = library.save(
        WorkflowBody.model_validate(definition(cover_template_id=template.template_id))
    )
    templates.delete(template.template_id)
    repo = OutputCollectionRepository(project, "collection")
    repo.write_highlight_result(
        {
            "collection_id": "collection",
            "asset_id": "asset",
            "notes": [],
            "outputs": [{"output_id": "o", "reason": "测试"}],
        }
    )
    result = read_highlights(project, "collection")
    configure_outputs(project, result, library.get(saved["workflow_id"]))
    stored = CoverStore(project, "collection", "o").read()
    assert stored is not None
    version, design = stored
    assert version == 1
    assert design.title == "设计封面"
    owned_image = directory / f"{design.background_image}.png"
    assert Image.open(owned_image).getpixel((0, 0)) == (0, 128, 0)
    configure_outputs(project, result, library.get(saved["workflow_id"]))
    stored = CoverStore(project, "collection", "o").read()
    assert stored is not None
    assert stored[0] == 1
