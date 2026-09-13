"""Export one existing output without invoking the language model."""

import json
from pathlib import Path
from urllib.parse import quote

from minicut.errors import UserInputError
from minicut.highlight_service import source_segments
from minicut.output_render import OutputRenderRequest, RenderOutputUseCase
from minicut.output_repository import OutputCollectionRepository
from minicut.render_command import SubtitleMode
from minicut.transcript import Transcript
from minicut.transcription_task import CancellationToken


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
    segments = source_segments(project, asset_id)
    plans = repository.read(segments).plans
    plan = next((plan for plan in plans if plan.output_id == output), None)
    if plan is None or plan.revision != revision:
        raise UserInputError("Output version changed; refresh before exporting")
    cancellation.raise_if_cancelled()
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
        )
    )
    base = f"/api/projects/{quote(project.name, safe='')}/media/exports/"
    return {
        "output_id": output,
        "revision": revision,
        "duration_ms": result.timeline.estimated_duration_ms,
        "media_url": base
        + quote(str(result.output_path.relative_to(project / "exports")), safe="/"),
        "subtitle_url": base
        + quote(str(result.subtitle_path.relative_to(project / "exports")), safe="/"),
    }
