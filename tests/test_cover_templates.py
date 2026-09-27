"""Shared cover templates do not carry another work's content or media links."""

import asyncio
import io
import json
import shutil
from pathlib import Path

import httpx
import pytest
from PIL import Image

from minicut.api import create_app
from minicut.cover_design import (
    CoverBox,
    CoverDesign,
    CoverStore,
    compose_cover,
    cover_fonts,
    design_directory,
)
from minicut.cover_templates import (
    CoverTemplateLibrary,
    TemplateNameConflict,
    TemplateNotFound,
)
from minicut.highlight_service import source_segments
from minicut.media import MediaAsset
from minicut.output_plan import (
    HighlightCandidate,
    OutputCollection,
    OutputItem,
    OutputPlan,
    OutputRole,
)
from minicut.output_repository import OutputCollectionRepository
from minicut.project import ProjectManifest, ProjectRepository
from minicut.transcript import Transcript, TranscriptSource, Word


@pytest.fixture
def projects(tmp_path: Path) -> Path:
    for name in ("one", "two"):
        project = tmp_path / name
        asset = MediaAsset("asset", str(project / "video.mp4"), 10000, (), "existing")
        ProjectRepository(project).create(ProjectManifest(name, (asset,)))
        transcript = Transcript(
            "t",
            TranscriptSource("asset", "mlx", "model"),
            "zh",
            (Word("w", "保留内容。", 1000, 3000),),
        )
        cache = project / ".minicut/transcripts/asset.json"
        cache.parent.mkdir(parents=True)
        cache.write_text(json.dumps({"transcript": transcript.to_dict()}))
        segments = source_segments(project, "asset")
        candidate = HighlightCandidate("c", "候选", "理由", (segments[0].segment_id,))
        plans = tuple(
            OutputPlan(
                identity,
                "c",
                f"{name} 的 {identity} 标题",
                (OutputItem(f"i-{identity}", segments[0].segment_id, OutputRole.BODY),),
            )
            for identity in ("a", "b")
        )
        OutputCollectionRepository(project, "collection").write(
            OutputCollection("collection", "asset", (candidate,), plans), segments
        )
    return tmp_path


def test_owned_background_and_applied_style_survive_update_delete_and_source_project_removal(
    projects: Path,
) -> None:
    library = CoverTemplateLibrary(projects)
    directory = design_directory(projects / "one", "collection", "a")
    directory.mkdir(parents=True)
    image_id = "a" * 32
    Image.new("RGB", (10, 10), "green").save(directory / f"{image_id}.png")
    original = CoverDesign(
        mode="design",
        title="绝不能复用的文字",
        frame_ms=1200,
        background_image=image_id,
        font_size=100,
        template_id="prior",
        template_name="prior",
    )
    template = library.save("知识封面", original, directory)
    assert template.style.background_image != image_id
    assert (
        not {"title", "frame_ms", "template_id", "template_name"}
        & template.style.model_dump().keys()
    )
    target = CoverDesign(title="第二条标题", frame_ms=1500)
    applied = library.apply(
        template, projects / "two", "collection", "b", target, "all"
    )
    assert applied.title == target.title and applied.frame_ms == target.frame_ms
    assert applied.template_id == template.template_id and applied.font_size == 100
    local_background = (
        design_directory(projects / "two", "collection", "b")
        / f"{applied.background_image}.png"
    )
    before = local_background.read_bytes()
    store = CoverStore(projects / "two", "collection", "b")
    store.save(applied, 0)
    library.save(
        template.name,
        original.model_copy(update={"font_size": 60, "background_image": None}),
        directory,
        template.template_id,
    )
    library.rename(template.template_id, "已改名")
    saved = store.read()
    assert saved and saved[1] == applied
    library.delete(template.template_id)
    shutil.rmtree(projects / "one")
    assert local_background.read_bytes() == before
    assert CoverTemplateLibrary(projects).list() == []
    if cover_fonts():
        frame = projects / "frame.png"
        Image.new("RGB", (100, 100), "blue").save(frame)
        image, _ = compose_cover(applied, frame, local_background)
        assert Image.open(io.BytesIO(image)).getpixel((0, 0)) == (0, 128, 0)


def test_title_only_apply_and_name_conflicts(projects: Path) -> None:
    library = CoverTemplateLibrary(projects)
    source = CoverDesign(
        mode="design",
        aspect_ratio="16:9",
        font_size=120,
        title_box=CoverBox(x=0.2),
        background_color="#ffffff",
    )
    template = library.save("English", source, projects)
    current = CoverDesign(
        title="当前文字",
        frame_ms=2200,
        background_color="#123456",
        aspect_ratio="1:1",
        frame=CoverBox(x=0.1),
    )
    applied = library.apply(
        template, projects / "two", "collection", "a", current, "title"
    )
    assert applied.font_size == 120 and applied.title_box == source.title_box
    assert (
        applied.background_color == current.background_color
        and applied.aspect_ratio == "1:1"
        and applied.frame == current.frame
    )
    assert applied.title == current.title and applied.frame_ms == 2200
    with pytest.raises(TemplateNameConflict):
        library.save("english", source, projects)
    other = library.save("另一个", source, projects)
    with pytest.raises(TemplateNameConflict):
        library.rename(other.template_id, "English")
    with pytest.raises(TemplateNotFound):
        library.save("不存在", source, projects, "missing")
    assert len(CoverTemplateLibrary(projects).list()) == 2


def test_api_shared_template_draft_application_and_batch_saved_versions(
    projects: Path,
) -> None:
    fonts = cover_fonts()
    if not fonts:
        pytest.skip("A local CJK font is required")

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(projects)),
            base_url="http://test",
        ) as client:
            source_route = "/api/projects/one/highlights/collection/outputs/a/cover"
            target_route = "/api/projects/two/highlights/collection/outputs/a/cover"
            stream = io.BytesIO()
            Image.new("RGB", (10, 10), "red").save(stream, format="PNG")
            background = (
                await client.post(
                    source_route + "/background", content=stream.getvalue()
                )
            ).json()["image_id"]
            design = CoverDesign(
                mode="design",
                title="来源文字",
                frame_ms=1200,
                font_id=next(iter(fonts)),
                background_image=background,
                font_size=110,
            )
            source = {
                "name": "共享封面",
                "project_id": "one",
                "collection_id": "collection",
                "output_id": "a",
                "revision": 1,
                "design": design.model_dump(),
            }
            created = await client.post("/api/cover-templates", json=source)
            assert created.status_code == 201
            template_id = created.json()["template_id"]
            assert (
                "title" not in created.json()["style"]
                and "frame_ms" not in created.json()["style"]
            )
            assert (
                await client.post("/api/cover-templates", json=source)
            ).status_code == 409
            assert (
                await client.post("/api/cover-templates", json={**source, "name": " "})
            ).status_code == 422
            current = CoverDesign(
                mode="design",
                title="手写的当前标题",
                frame_ms=2400,
                font_id=next(iter(fonts)),
                background_color="#123456",
            )
            await client.put(
                target_route,
                json={"revision": 1, "base_version": 0, "design": current.model_dump()},
            )
            draft = (
                await client.post(
                    target_route + "/apply-template",
                    json={
                        "revision": 1,
                        "template_id": template_id,
                        "mode": "all",
                        "design": current.model_dump(),
                    },
                )
            ).json()["design"]
            assert (
                draft["title"] == current.title
                and draft["frame_ms"] == current.frame_ms
                and draft["font_size"] == 110
            )
            saved = (await client.get(target_route)).json()
            assert (
                saved["version"] == 1
                and saved["design"]["font_size"] == current.font_size
            )
            rows = (
                await client.post(
                    "/api/projects/two/cover-template-batch",
                    json={
                        "collection_id": "collection",
                        "template_id": template_id,
                        "mode": "all",
                        "outputs": [
                            {"output_id": "a", "revision": 1},
                            {"output_id": "b", "revision": 99},
                        ],
                    },
                )
            ).json()
            assert (
                rows[0]["version"] == 2
                and rows[1]["version"] is None
                and rows[1]["error"]
            )
            applied = (await client.get(target_route)).json()
            assert (
                applied["design"]["title"] == current.title
                and applied["design"]["frame_ms"] == current.frame_ms
            )
            assert applied["design"]["font_size"] == 110
            assert (
                await client.get(
                    "/api/projects/two/highlights/collection/outputs/b/cover"
                )
            ).json()["version"] == 0
            source["design"] = design.model_copy(update={"font_size": 60}).model_dump()
            assert (
                await client.put(f"/api/cover-templates/{template_id}", json=source)
            ).status_code == 200
            assert (
                await client.patch(
                    f"/api/cover-templates/{template_id}", json={"name": "新名称"}
                )
            ).json()["name"] == "新名称"
            assert (
                await client.delete(f"/api/cover-templates/{template_id}")
            ).status_code == 204
            assert (await client.get(target_route)).json() == applied
            assert (
                await client.post(
                    target_route + "/apply-template",
                    json={
                        "revision": 1,
                        "template_id": template_id,
                        "design": current.model_dump(),
                    },
                )
            ).status_code == 404
            assert (
                await client.post(
                    "/api/projects/two/cover-template-batch",
                    json={
                        "collection_id": "collection",
                        "template_id": template_id,
                        "outputs": [
                            {"output_id": "a", "revision": 1},
                            {"output_id": "a", "revision": 1},
                        ],
                    },
                )
            ).status_code == 400

    asyncio.run(run())
