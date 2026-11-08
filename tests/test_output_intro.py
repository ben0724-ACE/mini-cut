import asyncio
import json
import wave
from array import array
from dataclasses import asdict, replace
from pathlib import Path

import httpx
import pytest
from PIL import ImageFont

from minicut.api import create_app
from minicut.highlight_service import source_segments
from minicut.intro import IntroSettings
from minicut.intro_render import wrap_intro_text, write_intro_music
from minicut.output_plan import OutputPlan
from minicut.output_repository import OutputCollectionRepository
from minicut.subtitle_font import available_subtitle_fonts, resolve_subtitle_font
from minicut.transcription_task import CancellationToken
from tests.test_cover_design import cover_project as cover_project


def test_long_intro_title_has_balanced_lines_without_losing_text() -> None:
    selected = resolve_subtitle_font()
    font = ImageFont.truetype(str(selected.path), 52, index=selected.index)
    title = "AI思考式推理为何需要亿倍算力：从检索到战略探索"
    lines = wrap_intro_text(title, font, 590, balanced=True)
    assert "".join(lines) == title
    assert len(lines) == 3
    assert (
        min(font.getlength(line) for line in lines)
        > max(font.getlength(line) for line in lines) * 0.65
    )


def test_intro_wrapping_keeps_punctuation_with_its_sentence() -> None:
    selected = resolve_subtitle_font()
    font = ImageFont.truetype(str(selected.path), 30, index=selected.index)
    text = "思考和解题需要大量推理，而不是重复知识。保留“必要背景”和限定。"
    lines = wrap_intro_text(text, font, 360)
    assert "".join(lines) == text
    assert all(
        not line.startswith(tuple("，。！？；：、”’）】》」』")) for line in lines
    )
    assert all(not line.endswith(tuple("“‘（【《「『")) for line in lines)
    assert all(font.getlength(line) <= 360 for line in lines)


def test_intro_round_trip_and_legacy_plan() -> None:
    from tests.test_output_plan import collection

    plan = collection().plans[0]
    intro = IntroSettings("导读", "一段介绍。", 4000, 100, False)
    current = replace(plan, intro=intro)
    assert OutputPlan.from_dict(current.to_dict()) == current
    legacy = plan.to_dict()
    legacy.pop("intro")
    assert OutputPlan.from_dict(legacy).intro is None
    old_intro = asdict(intro)
    old_intro.pop("motion")
    assert IntroSettings.from_dict(old_intro).motion is False
    legacy_intro = IntroSettings.from_dict({"title": "旧导读"})
    assert legacy_intro.motion_style == "fade"
    assert legacy_intro.music_version == 2
    assert legacy_intro.font_id is None
    assert legacy_intro.transition_ms == 0
    assert legacy_intro.motion_strength == 1
    assert plan.intro_duration_ms == 0
    with pytest.raises(ValueError, match="标题"):
        IntroSettings(" ")
    with pytest.raises(ValueError, match="精简"):
        IntroSettings("导读", "字" * 181)


@pytest.mark.parametrize("duration", [2000, 15000])
def test_studio_score_has_exact_length_stereo_and_a_quiet_exit(
    tmp_path: Path, duration: int
) -> None:
    path = tmp_path / "intro.wav"
    write_intro_music(path, duration, True, CancellationToken(), 2)
    with wave.open(str(path), "rb") as stream:
        assert stream.getframerate() == 48000
        assert stream.getnchannels() == 2
        assert stream.getnframes() == duration * 48
        pcm = array("h")
        pcm.frombytes(stream.readframes(stream.getnframes()))
    assert any(left != right for left, right in zip(pcm[::2], pcm[1::2], strict=True))
    assert 100 < max(abs(value) for value in pcm) < 32760
    assert max(abs(value) for value in pcm[-96:]) < 100


def test_intro_save_creates_revision_without_rendering_and_preserves_history(
    cover_project: Path,
) -> None:
    project = cover_project
    segments = source_segments(project, "asset", "collection")
    repository = OutputCollectionRepository(project, "collection")
    repository.write_highlight_result(
        {"asset_id": "asset", "outputs": [{"output_id": "o"}]}
    )
    original = repository.read(segments).plans[0]
    intro = IntroSettings(
        "为什么值得听",
        "从一个具体问题开始。",
        frame_ms=1200,
        font_id=next(iter(available_subtitle_fonts())),
    )
    route = "/api/projects/demo/highlights/collection/outputs/o/intro"

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(project.parent)),
            base_url="http://test",
        ) as client:
            invalid = await client.put(
                route,
                json={
                    "base_revision": 1,
                    "intro": {
                        **asdict(intro),
                        "frame_ms": 1900,
                    },
                },
            )
            assert invalid.status_code == 400
            assert repository.read(segments).plans[0] == original
            missing_font = await client.put(
                route,
                json={
                    "base_revision": 1,
                    "intro": {
                        **asdict(intro),
                        "font_id": "missing-local-font",
                    },
                },
            )
            assert missing_font.status_code == 400
            assert repository.read(segments).plans[0] == original
            saved = await client.put(
                route, json={"base_revision": 1, "intro": asdict(intro)}
            )
            assert saved.status_code == 200, saved.text
            output = saved.json()["outputs"][0]
            assert output["revision"] == 2
            assert output["duration_ms"] == 6800
            assert output["intro"] == asdict(intro)
            assert (
                repository.read(segments).plans[0].subtitle_style
                == original.subtitle_style
            )
            assert not (project / "exports").exists()
            assert not (project / ".minicut/covers").exists()
            conflict = await client.put(route, json={"base_revision": 1, "intro": None})
            assert conflict.status_code == 409
            versions = (
                await client.get(route.removesuffix("intro") + "versions")
            ).json()
            assert [version["intro"] for version in versions] == [None, asdict(intro)]
            disabled = await client.put(route, json={"base_revision": 2, "intro": None})
            assert disabled.status_code == 200
            assert disabled.json()["outputs"][0]["duration_ms"] == 1800

    asyncio.run(run())
    assert repository.read_plan(repository.read(segments), segments, "o", 1) == original
    assert (
        repository.read_plan(repository.read(segments), segments, "o", 2).intro == intro
    )
    assert json.loads(repository.path.read_text())["plans"][0]["intro"] is None


def test_export_preset_applies_subtitle_and_intro_in_one_saved_revision(
    cover_project: Path,
) -> None:
    project = cover_project
    repository = OutputCollectionRepository(project, "collection")
    segments = source_segments(project, "asset", "collection")
    original = repository.read(segments)
    plan = replace(
        original.plans[0],
        intro=IntroSettings("自己的标题", "自己的说明", frame_ms=1200),
    )
    repository.write(replace(original, plans=(plan,)), segments)
    repository.write_highlight_result(
        {"asset_id": "asset", "outputs": [{"output_id": "o"}]}
    )

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(project.parent)),
            base_url="http://test",
        ) as client:
            route = "/api/projects/demo/highlights/collection/outputs/o/appearance"
            options = {
                "subtitle_settings": {"subtitle_style": {"source_size": 72}},
                "intro_settings": {
                    "duration_ms": 8000,
                    "motion_strength": 1.8,
                    "transition_ms": 1000,
                },
            }
            saved = await client.put(
                route, json={"base_revision": 1, "options": options}
            )
            assert saved.status_code == 200, saved.text
            output = saved.json()["outputs"][0]
            assert output["revision"] == 2
            assert output["subtitle_style"]["source_size"] == 72
            assert output["intro"]["title"] == "自己的标题"
            assert output["intro"]["text"] == "自己的说明"
            assert output["intro"]["frame_ms"] == 1200
            assert output["intro"]["duration_ms"] == 8000
            assert output["intro"]["motion_strength"] == 1.8
            assert (
                await client.put(route, json={"base_revision": 1, "options": options})
            ).status_code == 409
            # A legacy preset omits intro settings and keeps existing content.
            legacy = await client.put(route, json={"base_revision": 2, "options": {}})
            assert legacy.json()["outputs"][0]["revision"] == 2
            assert legacy.json()["outputs"][0]["intro"] == output["intro"]
            disabled = await client.put(
                route,
                json={
                    "base_revision": 2,
                    "options": {"intro_settings": {"enabled": False}},
                },
            )
            assert disabled.json()["outputs"][0]["intro"] is None
            assert disabled.json()["outputs"][0]["revision"] == 3
            assert not (project / "exports").exists()

    asyncio.run(run())
