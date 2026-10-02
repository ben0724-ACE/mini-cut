"""Export one existing output without invoking the language model."""

import json
from dataclasses import asdict
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from minicut.cover_design import CoverDesign, render_cover, validate_design
from minicut.errors import UserInputError
from minicut.export_settings import ExportOptions, PreviewOptions
from minicut.highlight_service import source_segments
from minicut.output_plan import OutputPlan
from minicut.output_render import OutputRenderRequest, RenderOutputUseCase
from minicut.output_repository import OutputCollectionRepository
from minicut.output_timeline import compile_output_timeline
from minicut.project import ProjectRepository
from minicut.render_command import SubtitleMode
from minicut.render_profile import RenderProfile, source_dimensions
from minicut.renderer import FfmpegRenderer
from minicut.subtitle import parse_srt
from minicut.transcript import Transcript
from minicut.transcription_task import CancellationToken

_DEFAULT_PROFILE = RenderProfile()
RENDER_ENGINE_VERSION = 10


def _extract_cover(
    video_path: Path,
    cover_path: Path,
    cancellation: CancellationToken,
) -> None:
    """Publish the exact first decoded frame of the final exported video."""
    command = (
        "ffmpeg",
        "-nostdin",
        "-y",
        "-i",
        video_path.as_uri(),
        "-map",
        "0:v:0",
        "-frames:v",
        "1",
        "-q:v",
        "2",
        cover_path.as_uri(),
    )
    FfmpegRenderer().render_to_path(
        command,
        cover_path,
        timeout_seconds=120,
        cancellation=cancellation,
    )


def export_output(
    project: Path,
    collection: str,
    output: str,
    export_id: str,
    revision: int,
    subtitle_mode: str,
    audio_fade_ms: int,
    denoiser_id: str,
    cancellation: CancellationToken,
    profile: RenderProfile = _DEFAULT_PROFILE,
    preview: bool = False,
    cover_design: CoverDesign | None = None,
    cover_version: int | None = None,
) -> dict[str, object]:
    repository = OutputCollectionRepository(project, collection)
    try:
        asset_id = json.loads(repository.path.read_text(encoding="utf-8"))["asset_id"]
        cache = json.loads(
            (project / ".minicut/transcripts" / f"{asset_id}.json").read_text(
                encoding="utf-8"
            )
        )
        transcript = Transcript.from_dict(cache["transcript"])
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise UserInputError(
            "Output and transcription are required for export"
        ) from error
    segments = source_segments(project, asset_id, collection)
    plans = repository.read(segments).plans
    plan = next((plan for plan in plans if plan.output_id == output), None)
    if preview and plan is not None and plan.revision != revision:
        try:
            plan = OutputPlan.from_dict(
                json.loads(
                    repository.version_path(output, revision).read_text(
                        encoding="utf-8"
                    )
                )
            )
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise UserInputError("Requested preview version is unavailable") from error
    if plan is None or plan.revision != revision:
        raise UserInputError("Output version changed; refresh before exporting")
    if not preview and cover_design is not None:
        validate_design(project, collection, output, revision, cover_design)
    cancellation.raise_if_cancelled()
    asset = next(
        asset
        for asset in ProjectRepository(project).read().assets
        if asset.asset_id == asset_id
    )
    metadata = profile.metadata(*source_dimensions(Path(asset.source_path)))
    cover_data: bytes | None = None
    warnings: list[str] = []
    if not preview and cover_design is not None and cover_design.mode == "design":
        cover_data, warnings = render_cover(
            project, collection, output, revision, cover_design, "jpg", cancellation
        )
    result = RenderOutputUseCase().execute(
        OutputRenderRequest(
            project,
            collection,
            output,
            segments,
            transcript,
            timeout_seconds=3600,
            subtitle_mode=SubtitleMode(subtitle_mode),
            cancellation=cancellation,
            export_id=export_id,
            audio_fade_ms=audio_fade_ms,
            denoiser_id=denoiser_id,
            video_metadata=metadata,
            plan_revision=revision,
        )
    )
    cover_path: Path | None = None
    if not preview:
        cancellation.raise_if_cancelled()
        cover_path = result.output_path.with_name(
            f"{result.output_path.stem}-cover.jpg"
        )
        if cover_data is not None:
            cancellation.raise_if_cancelled()
            cover_path.write_bytes(cover_data)
        else:
            _extract_cover(result.output_path, cover_path, cancellation)
    base = f"/api/projects/{quote(project.name, safe='')}/media/exports/"
    response: dict[str, object] = {
        "output_id": output,
        "title": plan.title,
        "social_copy": plan.social_copy,
        "render_engine_version": RENDER_ENGINE_VERSION,
        "revision": revision,
        "width": metadata.width,
        "height": metadata.height,
        "aspect_ratio": profile.aspect_ratio,
        "resolution": profile.resolution,
        "fit": profile.fit,
        "crop_edges": list(profile.crop_edges),
        "duration_ms": result.timeline.estimated_duration_ms,
        "media_url": base
        + quote(str(result.output_path.relative_to(project / "exports")), safe="/"),
        "subtitle_url": base
        + quote(str(result.subtitle_path.relative_to(project / "exports")), safe="/"),
        "subtitle_warnings": list(result.subtitle_warnings),
    }
    if cover_path is not None:
        response["cover_version"] = cover_version
        response["cover_design"] = cover_design.model_dump() if cover_design else None
        response["cover_warnings"] = warnings
        response["cover_url"] = base + quote(
            str(cover_path.relative_to(project / "exports")), safe="/"
        )
    return response


def preview_output(
    project: Path,
    collection: str,
    output: str,
    revision: int,
    cancellation: CancellationToken,
    options: ExportOptions | None = None,
) -> dict[str, object]:
    options = options or PreviewOptions()
    profile = RenderProfile(
        **options.model_dump(include=set(RenderProfile.__dataclass_fields__))
    )
    repository = OutputCollectionRepository(project, collection)
    try:
        asset_id = json.loads(repository.path.read_text(encoding="utf-8"))["asset_id"]
        segments = source_segments(project, asset_id, collection)
        plan = next(
            plan for plan in repository.read(segments).plans if plan.output_id == output
        )
        if plan.revision != revision:
            plan = OutputPlan.from_dict(
                json.loads(
                    repository.version_path(output, revision).read_text(
                        encoding="utf-8"
                    )
                )
            )
        if plan.output_id != output or plan.revision != revision:
            raise ValueError("Preview version does not match")
    except (OSError, ValueError, KeyError, TypeError, StopIteration) as error:
        raise UserInputError("Requested preview version is unavailable") from error
    cancellation.raise_if_cancelled()
    asset = next(
        asset
        for asset in ProjectRepository(project).read().assets
        if asset.asset_id == asset_id
    )
    metadata = profile.metadata(*source_dimensions(Path(asset.source_path)))
    prefix = f"preview-r{RENDER_ENGINE_VERSION}-v{revision:04d}"
    record = repository.render_record_path(output, revision)
    for cached in sorted(record.parent.glob(f"{prefix}*/{record.name}"), reverse=True):
        path = (
            project
            / "exports"
            / collection
            / output
            / cached.parent.name
            / f"v{revision:04d}.mp4"
        )
        if not path.is_file() or not path.with_suffix(".srt").is_file():
            continue
        try:
            saved = json.loads(cached.read_text(encoding="utf-8"))
            matches = (
                OutputPlan.from_dict(saved["plan"]) == plan
                and saved.get("video_metadata")
                == json.loads(json.dumps(asdict(metadata)))
                and saved.get("subtitle_mode") == options.subtitle_mode
                and saved.get("audio_fade_ms") == options.audio_fade_ms
                and saved.get("denoiser_id") == options.denoiser_id
                and saved.get("preview_options") == options.model_dump()
            )
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if matches:
            base = f"/api/projects/{quote(project.name, safe='')}/media/exports/"
            result: dict[str, object] = {
                "output_id": output,
                "render_engine_version": RENDER_ENGINE_VERSION,
                "revision": revision,
                "reused": True,
                "duration_ms": compile_output_timeline(
                    plan, segments, asset_id
                ).estimated_duration_ms,
                "media_url": base
                + quote(str(path.relative_to(project / "exports")), safe="/"),
                "subtitle_url": base
                + quote(
                    str(path.with_suffix(".srt").relative_to(project / "exports")),
                    safe="/",
                ),
                "width": metadata.width,
                "height": metadata.height,
                "preview_options": options.model_dump(),
                "subtitle_warnings": saved.get("subtitle_warnings", []),
            }
            return _preview_subtitle_track(project, path, result, options)
    export_id = f"{prefix}-{uuid4().hex}"
    result = {
        **export_output(
            project,
            collection,
            output,
            export_id,
            revision,
            options.subtitle_mode,
            options.audio_fade_ms,
            options.denoiser_id,
            cancellation,
            profile,
            preview=True,
        ),
        "reused": False,
        "preview_options": options.model_dump(),
    }
    saved_record = record.parent / export_id / record.name
    if saved_record.is_file():
        saved = json.loads(saved_record.read_text(encoding="utf-8"))
        saved["preview_options"] = options.model_dump()
        repository.write_render_record(output, revision, saved, export_id)
    path = (
        project / "exports" / collection / output / export_id / f"v{revision:04d}.mp4"
    )
    return _preview_subtitle_track(project, path, result, options)


def _preview_subtitle_track(
    project: Path, video: Path, result: dict[str, object], options: ExportOptions
) -> dict[str, object]:
    if options.subtitle_mode != "soft":
        return result
    cues = parse_srt(video.with_suffix(".srt").read_text(encoding="utf-8"))

    def timestamp(ms: int) -> str:
        seconds, milliseconds = divmod(ms, 1000)
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"

    track = video.with_suffix(".vtt")
    track.write_text(
        "WEBVTT\n\n"
        + "\n\n".join(
            f"{timestamp(cue.start_ms)} --> {timestamp(cue.end_ms)}\n{cue.text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')}"
            for cue in cues
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        **result,
        "subtitle_track_url": f"/api/projects/{quote(project.name, safe='')}/media/exports/"
        + quote(str(track.relative_to(project / "exports")), safe="/"),
    }
