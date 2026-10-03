"""Saved presets and remembered overrides reach real FFmpeg exports."""

import asyncio
import json
import shutil
import subprocess
from pathlib import Path
from urllib.parse import unquote

import httpx
import pytest

from minicut.api import create_app
from minicut.media import StreamType
from minicut.probe import probe_media
from minicut.render_profile import source_dimensions
from tests.test_cover_design import cover_project as cover_project


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required")
def test_preset_and_batch_override_export_video_subtitles_and_original_audio(
    cover_project: Path,
) -> None:
    project = cover_project
    result_dir = project / ".minicut/highlight-results"
    result_dir.mkdir()
    (result_dir / "collection.json").write_text(
        json.dumps({"asset_id": "asset", "outputs": [{"output_id": "o"}]})
    )

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(project.parent)),
            base_url="http://test",
        ) as client:
            preset_response = await client.post(
                "/api/export-presets",
                json={"name": "裁剪原画软字幕", "options": {"crop_left": 50}},
            )
            assert preset_response.status_code == 201
            preset = preset_response.json()
            single = (
                "/api/projects/demo/highlights/collection/outputs/o/export-settings"
            )
            draft = {
                "options": preset["options"],
                "preset_id": preset["preset_id"],
                "preset_name": preset["name"],
            }
            assert (await client.put(single, json=draft)).status_code == 200
        # Restart the API before using the remembered settings.
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(project.parent)),
            base_url="http://test",
        ) as client:
            remembered = (await client.get(single)).json()["draft"]
            submitted = await client.post(
                "/api/projects/demo/tasks/output-export",
                json={
                    "collection_id": "collection",
                    "output_id": "o",
                    "revision": 1,
                    **remembered["options"],
                },
                headers={"Idempotency-Key": "remembered-soft"},
            )
            assert submitted.status_code == 202
            task = (await client.get("/api/projects/demo/tasks/remembered-soft")).json()
            assert task["status"] == "succeeded", task["error"]
            result = task["result"]
            video = (
                project
                / "exports"
                / unquote(result["media_url"].split("/media/exports/")[1])
            )
            assert source_dimensions(video) == (80, 120)
            assert any(
                stream.stream_type is StreamType.AUDIO
                for stream in probe_media(video).streams
            )
            assert abs(probe_media(video).duration_ms - result["duration_ms"]) < 100
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
            assert (await client.get(result["cover_url"])).status_code == 200
            assert (await client.get(result["subtitle_url"])).status_code == 200

            batch = "/api/projects/demo/highlights/collection/export-settings"
            batch_draft = {
                "options": {"aspect_ratio": "9:16", "subtitle_mode": "burned"},
                "overrides": {"o": {"aspect_ratio": "1:1", "resolution": 720}},
            }
            assert (await client.put(batch, json=batch_draft)).status_code == 200
            restored = (await client.get(batch)).json()["draft"]
            submitted = await client.post(
                "/api/projects/demo/tasks/output-export-batch",
                json={
                    "outputs": [
                        {
                            "collection_id": "collection",
                            "output_id": "o",
                            "revision": 1,
                            **restored["options"],
                            **restored["overrides"]["o"],
                        }
                    ]
                },
                headers={"Idempotency-Key": "remembered-burned"},
            )
            assert submitted.status_code == 202
            task = (
                await client.get("/api/projects/demo/tasks/remembered-burned-o")
            ).json()
            assert task["status"] == "succeeded", task["error"]
            burned = (
                project
                / "exports"
                / unquote(task["result"]["media_url"].split("/media/exports/")[1])
            )
            assert source_dimensions(burned) == (720, 720)
            assert any(
                stream.stream_type is StreamType.AUDIO
                for stream in probe_media(burned).streams
            )
            pixels = subprocess.check_output(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-ss",
                    "0.5",
                    "-i",
                    str(burned),
                    "-frames:v",
                    "1",
                    "-pix_fmt",
                    "rgb24",
                    "-f",
                    "rawvideo",
                    "-",
                ]
            )
            # White rendered subtitle pixels on the red source and black padding.
            assert any(
                min(pixels[index : index + 3]) > 200
                for index in range(0, len(pixels), 3)
            )
            audio = subprocess.check_output(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-i",
                    str(burned),
                    "-map",
                    "0:a:0",
                    "-t",
                    "0.2",
                    "-f",
                    "s16le",
                    "-",
                ]
            )
            assert any(audio)
            # A subsequent preset deletion leaves the first completed export intact.
            await client.delete(f"/api/export-presets/{preset['preset_id']}")
            old = (await client.get("/api/projects/demo/tasks/remembered-soft")).json()
            assert old["result"] == result
            assert video.is_file()

    asyncio.run(run())
