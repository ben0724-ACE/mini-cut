"""Deterministic single-work rendering; deliberately has no LLM dependency."""

import json
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

from minicut.application import TimelineRenderer
from minicut.errors import ProcessingError, UserInputError
from minicut.media import StreamType
from minicut.output_plan import OutputPlan
from minicut.output_repository import OutputCollectionRepository
from minicut.output_timeline import (
    OutputContextIssue,
    compile_output_timeline,
    inspect_output_context,
    map_output_words,
)
from minicut.project import ProjectRepository
from minicut.render_command import (
    RenderCommandBuilder,
    SubtitleMode,
    VideoOutputMetadata,
)
from minicut.renderer import FfmpegRenderer
from minicut.semantic_segment import SemanticSegment
from minicut.subtitle import build_readable_cues, render_srt
from minicut.subtitle_font import SubtitleFont, resolve_subtitle_font
from minicut.timeline import Timeline
from minicut.timeline_validation import TimelineTrackRequirements
from minicut.transcript import Transcript
from minicut.transcription_task import CancellationToken


@dataclass(frozen=True, slots=True)
class OutputRenderRequest:
    project_directory: Path
    collection_id: str
    output_id: str
    segments: tuple[SemanticSegment, ...]
    transcript: Transcript
    timeout_seconds: float = 60
    subtitle_mode: SubtitleMode = SubtitleMode.SOFT
    video_metadata: VideoOutputMetadata = VideoOutputMetadata()
    cancellation: CancellationToken | None = None


@dataclass(frozen=True, slots=True)
class OutputRenderResult:
    output_path: Path
    subtitle_path: Path
    record_path: Path
    timeline: Timeline
    context_issues: tuple[OutputContextIssue, ...]


class RenderOutputUseCase:
    def __init__(
        self,
        *,
        renderer: TimelineRenderer | None = None,
        command_builder: RenderCommandBuilder | None = None,
        subtitle_font_resolver: Callable[[], SubtitleFont] = resolve_subtitle_font,
    ) -> None:
        self._renderer = renderer or FfmpegRenderer()
        self._builder = command_builder or RenderCommandBuilder()
        self._font_resolver = subtitle_font_resolver

    def execute(self, request: OutputRenderRequest) -> OutputRenderResult:
        if request.timeout_seconds <= 0:
            raise UserInputError("Render timeout must be positive")
        repository = OutputCollectionRepository(
            request.project_directory, request.collection_id
        )
        collection = repository.read(request.segments)
        matches = [
            plan for plan in collection.plans if plan.output_id == request.output_id
        ]
        if not matches:
            raise UserInputError("Output plan does not exist")
        plan = matches[0]
        manifest = ProjectRepository(request.project_directory).read()
        assets = tuple(
            asset for asset in manifest.assets if asset.asset_id == collection.asset_id
        )
        if (
            len(assets) != 1
            or request.transcript.source.asset_id != collection.asset_id
        ):
            raise UserInputError(
                "Output source asset/transcript does not match the project"
            )
        timeline = compile_output_timeline(plan, request.segments, collection.asset_id)
        mapped = map_output_words(
            timeline,
            plan,
            request.segments,
            collection.asset_id,
            request.transcript.words,
        )
        subtitle_text = render_srt(
            build_readable_cues(mapped, timeline.estimated_duration_ms),
            timeline.estimated_duration_ms,
        )
        font = (
            self._font_resolver()
            if request.subtitle_mode is SubtitleMode.BURNED
            else None
        )
        destination_directory = (
            request.project_directory
            / "exports"
            / collection.collection_id
            / plan.output_id
        )
        output = destination_directory / f"v{plan.revision:04d}.mp4"
        subtitle = output.with_suffix(".srt")
        record_path = repository.render_record_path(plan.output_id, plan.revision)
        if any(
            Path(asset.source_path).resolve() in (output.resolve(), subtitle.resolve())
            for asset in manifest.assets
        ):
            raise UserInputError("Output must not overwrite source media")
        if record_path.is_file():
            try:
                record = cast(
                    Mapping[str, object],
                    json.loads(record_path.read_text(encoding="utf-8")),
                )
                previous = OutputPlan.from_dict(
                    cast(Mapping[str, object], record["plan"])
                )
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
                raise UserInputError("Output render record is invalid") from error
            if previous != plan:
                raise ValueError("Changed output plan requires a new revision")
        types = {stream.stream_type for stream in assets[0].streams}
        if StreamType.VIDEO not in types:
            raise UserInputError("Video output requires a video stream")
        requirements = TimelineTrackRequirements(
            require_video=True, require_audio=StreamType.AUDIO in types
        )
        issues = inspect_output_context(plan, request.segments)
        try:
            destination_directory.mkdir(parents=True, exist_ok=True)
            with TemporaryDirectory(
                prefix=".render-", dir=destination_directory
            ) as staging:
                staged_video = Path(staging) / "result.mp4"
                staged_subtitle = staged_video.with_suffix(".srt")
                command = self._builder.build_output_timeline(
                    timeline,
                    plan,
                    request.segments,
                    collection.asset_id,
                    assets,
                    str(staged_video),
                    requirements,
                    request.video_metadata,
                )
                self._renderer.render_to_path(
                    command,
                    staged_video,
                    timeout_seconds=request.timeout_seconds,
                    cancellation=request.cancellation,
                )
                staged_subtitle.write_text(subtitle_text, encoding="utf-8")
                command = self._builder.build_subtitle_output(
                    str(staged_video),
                    str(staged_subtitle),
                    str(staged_video),
                    request.subtitle_mode,
                    subtitle_font=font,
                )
                self._renderer.render_to_path(
                    command,
                    staged_video,
                    timeout_seconds=request.timeout_seconds,
                    cancellation=request.cancellation,
                )
                staged_subtitle.replace(subtitle)
                staged_video.replace(output)
            repository.write_render_record(
                plan.output_id,
                plan.revision,
                {
                    "plan": plan.to_dict(),
                    "timeline": timeline.to_dict(),
                    "asset_id": collection.asset_id,
                    "transcript_id": request.transcript.transcript_id,
                    "output_path": str(output.absolute()),
                    "subtitle_path": str(subtitle.absolute()),
                    "subtitle_mode": request.subtitle_mode.value,
                    "subtitle_font": None if font is None else font.to_record(),
                    "video_metadata": asdict(request.video_metadata),
                    "context_issues": [asdict(issue) for issue in issues],
                },
            )
        except OSError as error:
            raise ProcessingError(
                "Output render artifacts could not be written"
            ) from error
        return OutputRenderResult(
            output.absolute(),
            subtitle.absolute(),
            record_path.absolute(),
            timeline,
            issues,
        )
