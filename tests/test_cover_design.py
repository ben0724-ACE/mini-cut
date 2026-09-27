import asyncio
import io
import json
import subprocess
from pathlib import Path
from typing import Literal

import httpx
import pytest
from PIL import Image
from pydantic import ValidationError

import minicut.api as api_module
from minicut.api import create_app
from minicut.cover_design import (
    SIZES,
    CoverBox,
    CoverDesign,
    CoverStore,
    compose_cover,
    cover_fonts,
    normalize_background,
    render_cover,
    validate_design,
)
from minicut.errors import ProcessingError, UserInputError
from minicut.highlight_service import source_segments
from minicut.media import MediaAsset
from minicut.output_export import export_output
from minicut.output_plan import (
    HighlightCandidate,
    OutputCollection,
    OutputItem,
    OutputPlan,
    OutputRole,
)
from minicut.output_repository import OutputCollectionRepository
from minicut.probe import probe_media
from minicut.project import ProjectManifest, ProjectRepository
from minicut.render_profile import RenderProfile
from minicut.transcript import Transcript, TranscriptSource, Word
from minicut.transcription_task import CancellationToken


@pytest.fixture
def cover_project(tmp_path: Path) -> Path:
    project = tmp_path / "demo"
    project.mkdir()
    source = project / "素材.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=red:size=160x120:rate=25:duration=1",
            "-f",
            "lavfi",
            "-i",
            "color=blue:size=160x120:rate=25:duration=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-filter_complex",
            "[0:v][1:v]concat=n=2:v=1:a=0[v]",
            "-map",
            "[v]",
            "-map",
            "2:a",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(source),
        ],
        check=True,
        capture_output=True,
    )
    probe = probe_media(source)
    asset = MediaAsset("asset", str(source), probe.duration_ms, probe.streams, "test")
    ProjectRepository(project).create(ProjectManifest("demo", (asset,)))
    transcript = Transcript(
        "t",
        TranscriptSource("asset", "mlx", "model"),
        "zh",
        (Word("w", "设计封面。", 0, 1800),),
    )
    cache = project / ".minicut/transcripts/asset.json"
    cache.parent.mkdir(parents=True)
    cache.write_text(json.dumps({"transcript": transcript.to_dict()}))
    segments = source_segments(project, "asset")
    plan = OutputPlan(
        "o",
        "c",
        "设计封面",
        (OutputItem("i", segments[0].segment_id, OutputRole.BODY),),
    )
    OutputCollectionRepository(project, "collection").write(
        OutputCollection(
            "collection",
            "asset",
            (HighlightCandidate("c", "设计封面", "理由", (segments[0].segment_id,)),),
            (plan,),
        ),
        segments,
    )
    return project


@pytest.fixture
def font() -> str:
    fonts = cover_fonts()
    if not fonts:
        pytest.skip("A local CJK font is required")
    return next(iter(fonts))


@pytest.mark.parametrize("ratio", list(SIZES))
def test_dimensions_colors_and_title(
    ratio: Literal["9:16", "16:9", "1:1", "3:4"], tmp_path: Path, font: str
) -> None:
    frame = tmp_path / "frame.png"
    Image.new("RGB", (160, 120), "blue").save(frame)
    design = CoverDesign(
        mode="design",
        aspect_ratio=ratio,
        background_color="#123456",
        title="封面标题\n第二行",
        font_id=font,
    )
    data, warnings = compose_cover(design, frame, None)
    image = Image.open(io.BytesIO(data))
    w, h = SIZES[ratio]
    assert image.size == (w, h)
    assert image.getpixel((0, 0)) == (18, 52, 86)
    assert image.getpixel((w // 2, round(h * 0.37))) == (0, 0, 255)
    extrema = image.crop(
        (round(w * 0.08), round(h * 0.66), round(w * 0.92), round(h * 0.91))
    ).getextrema()
    assert isinstance(extrema, tuple) and isinstance(extrema[0], tuple)
    assert extrema[0][1] == 255
    assert not warnings


def test_background_crop_zoom_and_overflow(tmp_path: Path, font: str) -> None:
    frame = tmp_path / "frame.png"
    background = tmp_path / "background.png"
    Image.new("RGB", (16, 12), "blue").save(frame)
    image = Image.new("RGB", (200, 100), "red")
    image.paste(Image.new("RGB", (100, 100), "green"), (100, 0))
    image.save(background)
    design = CoverDesign(
        mode="design",
        aspect_ratio="1:1",
        background_scale=4,
        background_x=1,
        title="很长的标题" * 20,
        title_box=CoverBox(x=-0.1, y=0.9, width=0.4, height=0.05),
        font_id=font,
    )
    data, warnings = compose_cover(design, frame, background)
    assert Image.open(io.BytesIO(data)).getpixel((0, 0)) == (0, 128, 0)
    assert len(warnings) == 2


def test_validation_background_and_version_conflicts(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        CoverDesign(background_image="../secret")
    with pytest.raises(ValidationError):
        CoverBox(x=float("nan"))
    with pytest.raises(UserInputError):
        normalize_background(b"not an image")
    stream = io.BytesIO()
    Image.new("RGB", (20, 10), "red").save(stream, format="JPEG")
    assert (
        Image.open(io.BytesIO(normalize_background(stream.getvalue()))).format == "PNG"
    )
    store = CoverStore(tmp_path, "collection", "o")
    assert store.read() is None
    assert store.save(CoverDesign(title="旧标题"), 0) == 1
    assert store.save(CoverDesign(title="新标题"), 1) == 2
    old = store.read(1)
    assert old and old[1].title == "旧标题"
    with pytest.raises(UserInputError, match="其他页面"):
        store.save(CoverDesign(), 1)


def test_frame_provenance_actual_ffmpeg_and_cache(
    cover_project: Path, font: str
) -> None:
    design = CoverDesign(mode="design", frame_ms=1200, font_id=font, title="所选画面")
    data, _ = render_cover(cover_project, "collection", "o", 1, design)
    image = Image.open(io.BytesIO(data))
    pixel = image.getpixel((540, 710))
    assert isinstance(pixel, tuple) and pixel[2] > 240 and pixel[0] < 10
    cache = cover_project / ".minicut/covers/collection/o/frame-1200.png"
    stamp = cache.stat().st_mtime_ns
    render_cover(
        cover_project,
        "collection",
        "o",
        1,
        design.model_copy(update={"title": "改标题"}),
    )
    assert cache.stat().st_mtime_ns == stamp
    with pytest.raises(UserInputError, match="保留片段"):
        validate_design(
            cover_project,
            "collection",
            "o",
            1,
            design.model_copy(update={"frame_ms": 1900}),
        )
    with pytest.raises(UserInputError, match="版本"):
        validate_design(cover_project, "collection", "o", 2, design)


def test_api_save_upload_preview_download_and_snapshot_retry(
    cover_project: Path, font: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[object, ...]] = []

    def fake_export(*args: object) -> dict[str, object]:
        calls.append(args)
        if len(calls) == 1:
            raise ProcessingError("interrupted")
        return {"media_url": "/video", "subtitle_url": "/subtitles", "revision": 1}

    monkeypatch.setattr(api_module, "export_output", fake_export)

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(cover_project.parent)),
            base_url="http://test",
        ) as client:
            route = "/api/projects/demo/highlights/collection/outputs/o/cover"
            record = (await client.get(route)).json()
            assert record["version"] == 0 and record["design"]["title"] == "设计封面"
            assert (
                await client.post(route + "/background", content=b"invalid")
            ).status_code == 400
            stream = io.BytesIO()
            Image.new("RGB", (10, 10), "green").save(stream, format="WEBP")
            upload = await client.post(route + "/background", content=stream.getvalue())
            design = CoverDesign(
                mode="design",
                font_id=font,
                title="测试封面",
                background_image=upload.json()["image_id"],
            )
            payload = {"revision": 1, "base_version": 0, "design": design.model_dump()}
            assert (await client.put(route, json=payload)).json()["version"] == 1
            assert (await client.put(route, json=payload)).status_code == 400
            preview = await client.post(route + "/preview", json=payload)
            assert preview.status_code == 200
            download = await client.get(
                route + "/download?revision=1&version=1&format=png"
            )
            assert download.content == preview.content
            jpg = await client.get(route + "/download?revision=1&version=1&format=jpg")
            assert Image.open(io.BytesIO(jpg.content)).size == (1080, 1920)
            export = "/api/projects/demo/tasks/output-export"
            job = {"collection_id": "collection", "output_id": "o", "revision": 1}
            await client.post(export, json=job, headers={"Idempotency-Key": "export"})
            design.title = "后来改的标题"
            await client.put(
                route,
                json={**payload, "base_version": 1, "design": design.model_dump()},
            )
            assert (
                await client.post(
                    export, json=job, headers={"Idempotency-Key": "export"}
                )
            ).status_code == 202
            assert len(calls) == 1
            await client.post("/api/projects/demo/tasks/export/resume")
            assert len(calls) == 2
            assert (
                isinstance(calls[1][11], CoverDesign)
                and calls[1][11].title == "测试封面"
            )
            assert calls[1][12] == 1
            assert (
                await client.get(route + "/download?revision=1&version=1&format=png")
            ).content == preview.content

    asyncio.run(run())


def test_real_video_export_keeps_audio_and_custom_cover(
    cover_project: Path, font: str
) -> None:
    design = CoverDesign(
        mode="design",
        aspect_ratio="1:1",
        font_id=font,
        title="中文大标题",
        frame_ms=1200,
    )
    result = export_output(
        cover_project,
        "collection",
        "o",
        "export",
        1,
        "soft",
        0,
        "none",
        CancellationToken(),
        RenderProfile(resolution=720),
        False,
        design,
        1,
    )
    video = cover_project / "exports/collection/o/export/v0001.mp4"
    probe = probe_media(video)
    assert any(stream.stream_type.value == "audio" for stream in probe.streams)
    cover = video.with_name("v0001-cover.jpg")
    image = Image.open(cover)
    assert image.size == (1080, 1080)
    assert (
        result["cover_version"] == 1 and result["cover_design"] == design.model_dump()
    )
    before = cover.read_bytes()
    CoverStore(cover_project, "collection", "o").save(
        design.model_copy(update={"title": "新封面"}), 0
    )
    assert cover.read_bytes() == before


def test_real_export_uses_applied_template_after_library_deletion(
    cover_project: Path, font: str
) -> None:
    from minicut.cover_design import design_directory
    from minicut.cover_templates import CoverTemplateLibrary

    directory = design_directory(cover_project, "collection", "o")
    directory.mkdir(parents=True)
    image_id = "a" * 32
    Image.new("RGB", (16, 16), "green").save(directory / f"{image_id}.png")
    library = CoverTemplateLibrary(cover_project.parent)
    template = library.save(
        "可复用的封面",
        CoverDesign(
            mode="design",
            aspect_ratio="1:1",
            title="模板来源文字",
            frame_ms=0,
            font_id=font,
            background_image=image_id,
        ),
        directory,
    )
    applied = library.apply(
        template,
        cover_project,
        "collection",
        "o",
        CoverDesign(title="当前作品标题", frame_ms=1200),
        "all",
    )
    CoverStore(cover_project, "collection", "o").save(applied, 0)
    library.delete(template.template_id)

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(cover_project.parent)),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/projects/demo/tasks/output-export",
                json={
                    "collection_id": "collection",
                    "output_id": "o",
                    "revision": 1,
                    "resolution": 720,
                },
                headers={"Idempotency-Key": "template-export"},
            )
            assert response.status_code == 202
            task = (await client.get("/api/projects/demo/tasks/template-export")).json()
            assert task["status"] == "succeeded", task["error"]
            result = task["result"]
            assert result["cover_version"] == 1
            assert (
                result["cover_design"]["title"] == "当前作品标题"
                and result["cover_design"]["frame_ms"] == 1200
            )
            assert result["cover_design"]["template_name"] == template.name
            download = await client.get(result["cover_url"])
            image = Image.open(io.BytesIO(download.content))
            assert image.size == (1080, 1080)
            color = image.getpixel((0, 0))
            assert isinstance(color, tuple) and color[1] > 120 and color[0] < 10

    asyncio.run(run())
