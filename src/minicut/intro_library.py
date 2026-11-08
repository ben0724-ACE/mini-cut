"""Reusable intro appearance and project-local custom music imports."""

import json
from collections.abc import Callable
from dataclasses import asdict, replace
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Literal, TypeVar
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool
from starlette.responses import FileResponse

from minicut.errors import MiniCutError, UserInputError
from minicut.ffmpeg_paths import ffmpeg_file
from minicut.intro import IntroSettings
from minicut.media import StreamType
from minicut.probe import probe_media
from minicut.renderer import FfmpegRenderer
from minicut.subtitle_font import resolve_selected_subtitle_font

if TYPE_CHECKING:
    from minicut.output_plan import OutputPlan


class IntroStyle(BaseModel):
    """Only reusable settings: never another output's title, text or frame."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    enabled: bool = True
    duration_ms: int = Field(default=5000, ge=2000, le=15000, strict=True)
    font_id: str | None = Field(default=None, pattern=r"^[a-z0-9_-]{1,512}$")
    music: bool = True
    motion: bool = True
    motion_style: Literal["fade", "rise"] = "rise"
    motion_strength: float = Field(default=1, ge=0, le=2)
    transition_ms: int = Field(default=600, ge=0, le=1500, strict=True)
    audio_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")

    @classmethod
    def from_settings(cls, settings: IntroSettings) -> "IntroStyle":
        return cls.model_validate(
            {
                key: value
                for key, value in asdict(settings).items()
                if key in cls.model_fields
            }
        )

    def settings(self, title: str, text: str = "") -> IntroSettings:
        return IntroSettings(
            title=title,
            text=text,
            music_version=2,
            **self.model_dump(exclude={"enabled"}),
        )


def apply_intro_style(plan: "OutputPlan", style: IntroStyle | None) -> "OutputPlan":
    """Apply reusable appearance while keeping this output's editorial content."""
    if style is None:
        return plan
    if not style.enabled:
        return replace(plan, intro=None)
    previous = plan.intro
    intro = style.settings(
        previous.title if previous else plan.title,
        previous.text if previous else plan.social_copy or "",
    )
    if previous:
        intro = replace(intro, frame_ms=previous.frame_ms)
    return replace(plan, intro=intro)


def intro_audio_path(root: Path, identity: str) -> Path:
    import re

    if not re.fullmatch(r"[a-f0-9]{32}", identity):
        raise UserInputError("自定义 BGM 标识无效")
    path = root / ".minicut/intro-audio" / f"{identity}.m4a"
    if not path.is_file():
        raise UserInputError("自定义 BGM 已不存在，请重新上传或选择内置配乐")
    return path


def validate_intro_style(root: Path, style: IntroStyle) -> None:
    if style.font_id:
        resolve_selected_subtitle_font(style.font_id)
    if style.audio_id:
        intro_audio_path(root, style.audio_id)


def import_intro_audio(root: Path, data: bytes, name: str) -> dict[str, object]:
    directory = root / ".minicut/intro-audio"
    directory.mkdir(parents=True, exist_ok=True)
    identity = uuid4().hex
    destination = directory / f"{identity}.m4a"
    with TemporaryDirectory(prefix=".upload-", dir=directory) as temporary:
        source = Path(temporary) / "source.audio"
        source.write_bytes(data)
        staged = Path(temporary) / "music.m4a"
        # Store only the interval that any intro can use; long uploads stay cheap.
        FfmpegRenderer().render_to_path(
            (
                "ffmpeg",
                "-nostdin",
                "-y",
                "-protocol_whitelist",
                "file,pipe",
                "-format_whitelist",
                "mp3,wav,mov,matroska,ogg,flac,aac,aiff",
                "-i",
                ffmpeg_file(source),
                "-t",
                "15",
                "-map",
                "0:a:0",
                "-vn",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                ffmpeg_file(staged),
            ),
            staged,
            timeout_seconds=120,
        )
        metadata = probe_media(staged)
        if (
            not any(
                stream.stream_type is StreamType.AUDIO for stream in metadata.streams
            )
            or metadata.duration_ms <= 0
        ):
            raise UserInputError("文件中没有可读取的音轨")
        staged.replace(destination)
    record: dict[str, object] = {
        "audio_id": identity,
        "name": Path(name).name[:200] or "自定义 BGM",
        "duration_ms": min(15000, metadata.duration_ms),
    }
    destination.with_suffix(".json").write_text(
        json.dumps(record, ensure_ascii=False), encoding="utf-8"
    )
    return record


T = TypeVar("T")


def checked(operation: Callable[[], T]) -> T:
    try:
        return operation()
    except MiniCutError as error:
        raise HTTPException(400, str(error)) from error
    except OSError as error:
        raise HTTPException(
            500, "无法读取或保存导读素材，请检查本地目录后重试"
        ) from error


def intro_router(root: Path) -> APIRouter:
    router = APIRouter()

    @router.get("/api/intro-audio/{identity}")
    def audio_record(  # pyright: ignore[reportUnusedFunction]
        identity: str,
    ) -> dict[str, object]:
        path = checked(lambda: intro_audio_path(root, identity))
        return json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))

    @router.get("/api/intro-audio/{identity}/media")
    def audio_media(  # pyright: ignore[reportUnusedFunction]
        identity: str,
    ) -> FileResponse:
        return FileResponse(
            checked(lambda: intro_audio_path(root, identity)), media_type="audio/mp4"
        )

    @router.post("/api/intro-audio", status_code=201)
    async def upload_audio(  # pyright: ignore[reportUnusedFunction]
        request: Request, name: str = "自定义 BGM"
    ) -> dict[str, object]:
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 25 * 1024 * 1024:
                raise HTTPException(413, "BGM 文件不能超过 25 MB")
        if not data:
            raise HTTPException(422, "请选择音频文件")
        return await run_in_threadpool(
            checked, lambda: import_intro_audio(root, bytes(data), name)
        )

    return router
