"""Local music and reusable styles keep content bound to each output."""

import asyncio
import wave
from array import array
from pathlib import Path

import httpx
import pytest

from minicut.api import create_app
from minicut.intro import IntroSettings
from minicut.intro_library import IntroStyle, intro_audio_path
from minicut.intro_render import write_intro_music
from minicut.transcription_task import CancellationToken


def test_style_excludes_content_and_validates_effect_ranges() -> None:
    style = IntroStyle.from_settings(IntroSettings("作品甲", "只属于甲", frame_ms=1200))
    assert (
        not {"title", "text", "frame_ms", "music_version"} & style.model_dump().keys()
    )
    assert style.settings("作品乙", "乙的简介").title == "作品乙"
    for patch in (
        {"motion_strength": 2.1},
        {"motion_strength": float("nan")},
        {"transition_ms": -1},
    ):
        with pytest.raises(ValueError):
            IntroStyle.model_validate(patch)
    for strength in (0, 2):
        assert (
            IntroSettings("导读", motion_strength=strength).motion_strength == strength
        )


def test_custom_audio_and_presets_round_trip_without_model_calls(
    tmp_path: Path,
) -> None:
    path = tmp_path / "short.wav"
    samples = array("h", [1000, -1000] * 4800)
    with wave.open(str(path), "wb") as stream:
        stream.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
        stream.writeframes(samples.tobytes())

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(tmp_path)),
            base_url="http://test",
        ) as client:
            assert (
                await client.post("/api/intro-audio", content=b"")
            ).status_code == 422
            assert (
                await client.post(
                    "/api/intro-audio",
                    content=b"#EXTM3U\nhttps://example.com/audio.mp3",
                )
            ).status_code == 400
            uploaded = await client.post(
                "/api/intro-audio?name=我的音乐.wav", content=path.read_bytes()
            )
            assert uploaded.status_code == 201, uploaded.text
            audio = uploaded.json()
            assert audio["name"] == "我的音乐.wav"
            assert (
                await client.get(f"/api/intro-audio/{audio['audio_id']}")
            ).json() == audio
            assert (
                await client.get(f"/api/intro-audio/{audio['audio_id']}/media")
            ).headers["content-type"] == "audio/mp4"
            body = {
                "name": "科技导读",
                "options": {
                    "intro_settings": {
                        "audio_id": audio["audio_id"],
                        "motion_strength": 1.5,
                        "transition_ms": 800,
                    }
                },
            }
            created = await client.post("/api/export-presets", json=body)
            assert created.status_code == 201, created.text
            preset = created.json()
            assert (await client.get("/api/export-presets")).json() == [preset]
            assert (
                await client.post("/api/export-presets", json=body)
            ).status_code == 409
            route = f"/api/export-presets/{preset['preset_id']}"
            renamed = await client.patch(route, json={"name": "另一个名字"})
            assert renamed.json()["options"] == preset["options"]
            updated = await client.put(
                route,
                json={
                    **body,
                    "options": {
                        **preset["options"],
                        "intro_settings": {
                            **preset["options"]["intro_settings"],
                            "motion_strength": 0,
                        },
                    },
                },
            )
            assert updated.json()["options"]["intro_settings"]["motion_strength"] == 0
            assert (await client.delete(route)).status_code == 200
            # A saved output/workflow keeps its immutable music reference after preset deletion.
            wav = tmp_path / "loop.wav"
            write_intro_music(
                wav,
                2000,
                True,
                CancellationToken(),
                custom_audio=intro_audio_path(tmp_path, audio["audio_id"]),
            )
            with wave.open(str(wav), "rb") as stream:
                assert stream.getnframes() == 96000
                stream.setpos(48000)
                assert any(array("h", stream.readframes(4800)))
            assert (
                await client.post(
                    "/api/export-presets",
                    json={
                        **body,
                        "options": {"intro_settings": {"audio_id": "0" * 32}},
                    },
                )
            ).status_code == 400
            assert (
                await client.post(
                    "/api/export-presets",
                    json={
                        **body,
                        "options": {"intro_settings": {"title": "不应复制文字"}},
                    },
                )
            ).status_code == 422

    asyncio.run(run())
