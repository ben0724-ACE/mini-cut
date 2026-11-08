"""Exercise actual frames, PCM audio, soft/burned subtitles and preview recovery."""

from __future__ import annotations

import json
import math
import subprocess
from array import array
from dataclasses import asdict, replace
from pathlib import Path
from typing import Literal, cast
from urllib.parse import unquote

import pytest

from minicut.export_settings import ExportOptions
from minicut.highlight_service import source_segments
from minicut.intro import IntroSettings
from minicut.output_export import export_output, preview_output
from minicut.output_plan import OutputRole
from minicut.output_repository import OutputCollectionRepository
from minicut.probe import probe_media
from minicut.render_profile import RenderProfile
from minicut.subtitle import parse_srt
from minicut.subtitle_font import available_subtitle_fonts
from minicut.transcription_task import CancellationToken
from tests.integration.test_preview_export_parity import frame
from tests.test_cover_design import cover_project as cover_project


def pcm(path: Path, start: float = 0, duration: float | None = None) -> array[int]:
    args = ["ffmpeg", "-v", "error", "-i", str(path), "-ss", str(start)]
    if duration is not None:
        args.extend(("-t", str(duration)))
    data = subprocess.check_output(
        [*args, "-map", "0:a:0", "-ar", "48000", "-ac", "1", "-f", "s16le", "-"]
    )
    result = array("h")
    result.frombytes(data)
    return result


@pytest.mark.parametrize(
    "subtitle_mode,portrait,hook,music,motion",
    [
        ("burned", True, True, True, True),
        ("soft", False, False, True, True),
        ("soft", True, False, False, True),
        ("burned", False, False, False, False),
    ],
)
def test_intro_preserves_speech_and_offsets_subtitles_in_preview_and_export(
    cover_project: Path,
    subtitle_mode: Literal["soft", "burned"],
    portrait: bool,
    hook: bool,
    music: bool,
    motion: bool,
) -> None:
    project = cover_project
    segments = source_segments(project, "asset", "collection")
    repository = OutputCollectionRepository(project, "collection")
    collection = repository.read(segments)
    plan = collection.plans[0]
    if subtitle_mode == "burned":
        plan = replace(
            plan,
            items=(
                replace(
                    plan.items[0],
                    translation_text="Understand the background first.",
                    translation_language="en",
                ),
            ),
            subtitle_mode="bilingual",
        )
    if not music:
        plan = replace(plan, workflow="speech_cleanup")
    if hook:
        plan = replace(
            plan,
            items=(
                replace(
                    plan.items[0],
                    instance_id="hook",
                    role=OutputRole.HOOK,
                    source_start_ms=0,
                    source_end_ms=400,
                ),
                *plan.items,
            ),
            hook_transition_kind="tv_static",
        )
    repository.write(replace(collection, plans=(plan,)), segments)
    ratio = "9:16" if portrait else "16:9"
    profile = RenderProfile(aspect_ratio=ratio, resolution=720)
    token = CancellationToken()
    baseline = export_output(
        project, "collection", "o", "base", 1, subtitle_mode, 0, "none", token, profile
    )
    intro = IntroSettings(
        "一个值得理解的问题", "先看背景，再听原话。", 2000, 1200, music, motion
    )
    if portrait and hook:
        intro = replace(intro, font_id=next(iter(available_subtitle_fonts())))
    plan = replace(plan, intro=intro, revision=2)
    repository.write(replace(collection, plans=(plan,)), segments)
    options = ExportOptions(
        aspect_ratio=ratio, resolution=720, subtitle_mode=subtitle_mode
    )
    preview = preview_output(project, "collection", "o", 2, token, options)
    exported = export_output(
        project, "collection", "o", "intro", 2, subtitle_mode, 0, "none", token, profile
    )

    def local(result: dict[str, object], key: str) -> Path:
        return (
            project / "exports" / unquote(str(result[key]).split("/media/exports/")[1])
        )

    video, preview_video = local(exported, "media_url"), local(preview, "media_url")
    assert exported["intro"] == asdict(intro)
    assert exported["duration_ms"] == cast(int, baseline["duration_ms"]) + 2000
    assert abs(probe_media(video).duration_ms - cast(int, exported["duration_ms"])) < 60
    assert preview["duration_ms"] == exported["duration_ms"]
    assert pcm(video) == pcm(preview_video)
    for second in ("0", "1.0", "2.3", "3.2"):
        assert frame(video, second) == frame(preview_video, second)
    first = frame(video, "0")
    # The selected source frame is blue; the background is darkened, not black.
    assert first[2] > first[0] + 30

    def bright_pixels(pixels: bytes) -> int:
        return sum(value > 200 for value in pixels[::3])

    if motion:
        early = frame(video, "0.45")
        middle = frame(video, "0.8")
        ending = frame(video, "1.9")
        assert bright_pixels(first) == 0
        assert 0 < bright_pixels(early) < bright_pixels(middle)
        assert bright_pixels(ending) < bright_pixels(middle) // 4
    else:
        assert bright_pixels(first) > 0
    before = parse_srt(local(baseline, "subtitle_url").read_text())
    after = parse_srt(local(exported, "subtitle_url").read_text())
    assert [(cue.start_ms + 2000, cue.end_ms + 2000, cue.text) for cue in before] == [
        (cue.start_ms, cue.end_ms, cue.text) for cue in after
    ]
    assert (
        local(preview, "subtitle_url").read_bytes()
        == local(exported, "subtitle_url").read_bytes()
    )
    if subtitle_mode == "soft":
        assert "00:00:02.000" in local(preview, "subtitle_track_url").read_text()
    reference = pcm(local(baseline, "media_url"), 0.9, 0.5)
    speech = pcm(video, 2.9, 0.5)
    correlation = sum(
        a * b for a, b in zip(reference, speech, strict=True)
    ) / math.sqrt(sum(a * a for a in reference) * sum(b * b for b in speech))
    assert correlation > 0.99
    intro_audio = pcm(video, 0.2, 0.5)
    assert (max(abs(value) for value in intro_audio) > 100) is music
    cached = preview_output(project, "collection", "o", 2, token, options)
    assert cached["reused"] is True
    assert cached["media_url"] == preview["media_url"]
    assert cached["duration_ms"] == exported["duration_ms"]
    record = json.loads(
        (
            repository.render_record_path("o", 2).parent
            / "intro"
            / repository.render_record_path("o", 2).name
        ).read_text()
    )
    assert record["timeline"]["clips"][0]["output_range"]["start_ms"] == 2000


def test_transition_reaches_black_then_restores_main_picture(
    cover_project: Path,
) -> None:
    repository = OutputCollectionRepository(cover_project, "collection")
    segments = source_segments(cover_project, "asset", "collection")
    collection = repository.read(segments)
    plan = replace(
        collection.plans[0],
        intro=IntroSettings(
            "转黑检验", duration_ms=2000, transition_ms=1000, motion_strength=2
        ),
        revision=2,
    )
    repository.write(replace(collection, plans=(plan,)), segments)
    result = preview_output(
        cover_project,
        "collection",
        "o",
        2,
        CancellationToken(),
        ExportOptions(resolution=720),
    )
    video = (
        cover_project
        / "exports"
        / unquote(str(result["media_url"]).split("/media/exports/")[1])
    )

    def brightness(second: str) -> float:
        pixels = frame(video, second)
        return sum(pixels) / len(pixels)

    assert brightness("1.4") > brightness("1.8") > brightness("2.0")
    assert brightness("2.0") < 3
    assert brightness("2.0") < brightness("2.2") < brightness("2.5")


@pytest.mark.parametrize("enabled", [True, False])
def test_export_preset_intro_matches_preview_export_and_keeps_saved_editorial_content(
    cover_project: Path, enabled: bool
) -> None:
    from minicut.intro_library import IntroStyle

    project = cover_project
    segments = source_segments(project, "asset", "collection")
    repository = OutputCollectionRepository(project, "collection")
    collection = repository.read(segments)
    plan = replace(
        collection.plans[0],
        revision=2,
        intro=IntroSettings(
            "保留编辑标题", "保留编辑说明", duration_ms=2000, frame_ms=1200
        ),
    )
    repository.write(replace(collection, plans=(plan,)), segments)
    style = IntroStyle(enabled=enabled, duration_ms=3000, motion_strength=1.5)
    options = ExportOptions(
        resolution=720, intro_settings=style, subtitle_mode="burned"
    )
    token = CancellationToken()
    preview = preview_output(project, "collection", "o", 2, token, options)
    exported = export_output(
        project,
        "collection",
        "o",
        "preset-export",
        2,
        "burned",
        0,
        "none",
        token,
        RenderProfile(resolution=720),
        intro_settings=style,
    )
    assert (
        exported["duration_ms"]
        == preview["duration_ms"]
        == 1800 + (3000 if enabled else 0)
    )
    assert exported["intro"] == preview["intro"]
    if enabled:
        assert cast(dict[str, object], exported["intro"])["title"] == "保留编辑标题"
        assert cast(dict[str, object], exported["intro"])["frame_ms"] == 1200
    else:
        assert exported["intro"] is None
    video = (
        project
        / "exports"
        / unquote(str(exported["media_url"]).split("/media/exports/")[1])
    )
    preview_video = (
        project
        / "exports"
        / unquote(str(preview["media_url"]).split("/media/exports/")[1])
    )
    assert frame(video, "0.8") == frame(preview_video, "0.8")
    assert pcm(video) == pcm(preview_video)
    assert repository.read(segments).plans[0] == plan
