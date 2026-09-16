"""Export one existing output without invoking the language model."""

import json
from pathlib import Path
from urllib.parse import quote

from minicut.errors import UserInputError
from minicut.highlight_service import source_segments
from minicut.output_plan import OutputPlan
from minicut.output_render import OutputRenderRequest, RenderOutputUseCase
from minicut.output_repository import OutputCollectionRepository
from minicut.output_timeline import compile_output_timeline
from minicut.project import ProjectRepository
from minicut.render_command import SubtitleMode, VideoOutputMetadata
from minicut.render_profile import RenderProfile, source_dimensions
from minicut.transcript import Transcript
from minicut.transcription_task import CancellationToken

_DEFAULT_PROFILE = RenderProfile()
RENDER_ENGINE_VERSION = 5


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
    cancellation.raise_if_cancelled()
    asset = next(
        asset
        for asset in ProjectRepository(project).read().assets
        if asset.asset_id == asset_id
    )
    metadata = profile.metadata(*source_dimensions(Path(asset.source_path)))
    if preview:
        scale = min(1, 640 / max(metadata.width, metadata.height))
        metadata = VideoOutputMetadata(
            max(2, int(metadata.width * scale) // 2 * 2),
            max(2, int(metadata.height * scale) // 2 * 2),
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
    base = f"/api/projects/{quote(project.name, safe='')}/media/exports/"
    return {
        "output_id": output,
        "render_engine_version": RENDER_ENGINE_VERSION,
        "revision": revision,
        "width": metadata.width,
        "height": metadata.height,
        "aspect_ratio": profile.aspect_ratio,
        "resolution": profile.resolution,
        "fit": profile.fit,
        "duration_ms": result.timeline.estimated_duration_ms,
        "media_url": base
        + quote(str(result.output_path.relative_to(project / "exports")), safe="/"),
        "subtitle_url": base
        + quote(str(result.subtitle_path.relative_to(project / "exports")), safe="/"),
    }


def preview_output(
    project: Path,
    collection: str,
    output: str,
    revision: int,
    cancellation: CancellationToken,
) -> dict[str, object]:
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
    export_id = f"preview-r{RENDER_ENGINE_VERSION}-v{revision:04d}"
    path = (
        project / "exports" / collection / output / export_id / f"v{revision:04d}.mp4"
    )
    record = repository.render_record_path(output, revision)
    record = record.parent / export_id / record.name
    if path.is_file() and path.with_suffix(".srt").is_file() and record.is_file():
        saved = json.loads(record.read_text(encoding="utf-8"))
        if OutputPlan.from_dict(saved["plan"]) == plan:
            base = f"/api/projects/{quote(project.name, safe='')}/media/exports/"
            return {
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
            }
    return {
        **export_output(
            project,
            collection,
            output,
            export_id,
            revision,
            "burned",
            0,
            "none",
            cancellation,
            preview=True,
        ),
        "reused": False,
    }
