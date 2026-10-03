"""Real previews retain the exact output geometry, subtitle layout and audio."""

import asyncio
import json
import subprocess
from dataclasses import asdict, replace
from pathlib import Path
from typing import cast
from urllib.parse import unquote

import httpx
import pytest

from minicut.api import create_app
from minicut.highlight_service import source_segments
from minicut.media import StreamType
from minicut.output_plan import OutputRole
from minicut.output_repository import OutputCollectionRepository
from minicut.probe import probe_media
from minicut.render_profile import source_dimensions
from minicut.subtitle import parse_srt
from minicut.subtitle_style import SubtitleStyle
from tests.test_cover_design import cover_project as cover_project


def frame(path: Path, second: str) -> bytes:
    return subprocess.check_output(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            second,
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-pix_fmt",
            "rgb24",
            "-f",
            "rawvideo",
            "-",
        ]
    )


def audio(path: Path) -> bytes:
    return subprocess.check_output(
        ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0", "-f", "s16le", "-"]
    )


@pytest.mark.parametrize("subtitle_mode", ["burned", "soft"])
@pytest.mark.parametrize("complete_preset", [False, True])
def test_preview_matches_export_pixels_subtitle_timing_and_audio(
    cover_project: Path, subtitle_mode: str, complete_preset: bool
) -> None:
    project = cover_project
    segments = source_segments(project, "asset", "collection")
    repository = OutputCollectionRepository(project, "collection")
    collection = repository.read(segments)
    plan = collection.plans[0]
    body = replace(
        plan.items[0],
        translation_text="A complete translated sentence.",
        translation_language="en",
    )
    hook = replace(
        body,
        instance_id="hook",
        role=OutputRole.HOOK,
        source_start_ms=0,
        source_end_ms=500,
    )
    plan = replace(
        plan,
        items=(hook, body),
        subtitle_mode="bilingual",
        subtitle_source_scale=1.2,
        subtitle_translation_scale=0.9,
        subtitle_horizontal_percent=45,
        subtitle_bottom_percent=18,
        subtitle_order="translation_first",
        hook_transition_ms=300,
        hook_transition_kind="tv_static",
    )
    repository.write(replace(collection, plans=(plan,)), segments)
    repository.write_highlight_result(
        {"asset_id": "asset", "outputs": [{"output_id": "o"}]}
    )

    def local(url: str) -> Path:
        return project / "exports" / unquote(url.split("/media/exports/")[1])

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(project.parent)),
            base_url="http://test",
        ) as client:
            options: dict[str, object] = {
                "aspect_ratio": "9:16",
                "resolution": 720,
                "fit": "crop",
                "crop_left": 10,
                "crop_top": 5,
                "subtitle_mode": subtitle_mode,
                "audio_fade_ms": 100,
                "denoiser_id": "afftdn",
            }
            if complete_preset:
                options["subtitle_settings"] = {
                    "subtitle_mode": "bilingual",
                    "subtitle_source_scale": 1,
                    "subtitle_translation_scale": 1,
                    "subtitle_horizontal_percent": 55,
                    "subtitle_bottom_percent": 22,
                    "subtitle_order": "source_first",
                    "subtitle_style": asdict(
                        SubtitleStyle(
                            source_size=80,
                            translation_size=40,
                            text_color="#ffff00",
                            stroke_width=3,
                            shadow_width=2,
                            background_enabled=True,
                            background_opacity=50,
                        )
                    ),
                }
                saved = await client.post(
                    "/api/export-presets", json={"name": "Full", "options": options}
                )
                assert saved.status_code == 201
                options = saved.json()["options"]
            body = {
                "collection_id": "collection",
                "output_id": "o",
                "revision": 1,
                **options,
            }
            assert (
                await client.post(
                    "/api/projects/demo/tasks/output-preview",
                    json=body,
                    headers={"Idempotency-Key": "preview"},
                )
            ).status_code == 202
            preview_task = (await client.get("/api/projects/demo/tasks/preview")).json()
            assert preview_task["status"] == "succeeded", preview_task["error"]
            preview = preview_task["result"]
            assert (
                await client.post(
                    "/api/projects/demo/tasks/output-export",
                    json=body,
                    headers={"Idempotency-Key": "export"},
                )
            ).status_code == 202
            export_task = (await client.get("/api/projects/demo/tasks/export")).json()
            assert export_task["status"] == "succeeded", export_task["error"]
            exported = export_task["result"]
            preview_video, export_video = (
                local(preview["media_url"]),
                local(exported["media_url"]),
            )
            assert (
                source_dimensions(preview_video)
                == source_dimensions(export_video)
                == (720, 1280)
            )
            for second in ("0.2", "0.65", "1.2"):
                assert frame(preview_video, second) == frame(export_video, second)
            assert audio(preview_video) == audio(export_video)
            assert any(
                stream.stream_type is StreamType.AUDIO
                for stream in probe_media(preview_video).streams
            )
            assert (
                local(preview["subtitle_url"]).read_text()
                == local(exported["subtitle_url"]).read_text()
            )
            assert repository.read(segments).plans[0] == plan
            if complete_preset:
                record = next(
                    repository.render_record_path("o", 1).parent.glob(
                        f"{export_video.parent.name}/*.json"
                    )
                )
                rendered_plan = json.loads(record.read_text())["plan"]
                assert (
                    rendered_plan["subtitle_style"]
                    == cast(dict[str, object], options["subtitle_settings"])[
                        "subtitle_style"
                    ]
                )
                assert rendered_plan["subtitle_bottom_percent"] == 22
                assert exported["subtitle_settings"] == options["subtitle_settings"]
            assert preview["duration_ms"] == exported["duration_ms"] == 2600
            assert not preview_video.with_name("v0001-cover.jpg").exists()
            if subtitle_mode == "soft":
                track = await client.get(preview["subtitle_track_url"])
                assert track.status_code == 200 and track.headers[
                    "content-type"
                ].startswith("text/vtt")
                assert track.text.startswith("WEBVTT") and "A complete" in track.text
                for cue in parse_srt(local(preview["subtitle_url"]).read_text()):
                    assert cue.text in track.text
                muxed = subprocess.check_output(
                    [
                        "ffmpeg",
                        "-v",
                        "error",
                        "-i",
                        str(preview_video),
                        "-map",
                        "0:s:0",
                        "-f",
                        "srt",
                        "-",
                    ],
                    text=True,
                )
                assert "A complete" in muxed
            else:
                assert "subtitle_track_url" not in preview
            # The same configuration reuses its render; a changed crop gets a separate file.
            assert (
                await client.post(
                    "/api/projects/demo/tasks/output-preview",
                    json=body,
                    headers={"Idempotency-Key": "reuse"},
                )
            ).status_code == 202
            reused = (await client.get("/api/projects/demo/tasks/reuse")).json()[
                "result"
            ]
            assert reused["reused"] and reused["media_url"] == preview["media_url"]
            assert (
                await client.get(
                    "/api/projects/demo/highlights/collection/outputs/o/preview-task",
                    params={
                        "revision": 1,
                        **{
                            key: str(value)
                            for key, value in options.items()
                            if key != "subtitle_settings"
                        },
                        "subtitle_settings": json.dumps(
                            options.get("subtitle_settings")
                        ),
                    },
                )
            ).json()["task_id"] == "reuse"
            assert (
                await client.get(
                    "/api/projects/demo/highlights/collection/outputs/o/preview-task",
                    params={
                        "revision": 1,
                        **{
                            key: str(value)
                            for key, value in options.items()
                            if key != "subtitle_settings"
                        },
                        "crop_left": 11,
                        "subtitle_settings": json.dumps(
                            options.get("subtitle_settings")
                        ),
                    },
                )
            ).json() is None

    asyncio.run(run())
