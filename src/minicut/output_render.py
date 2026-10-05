"""Deterministic single-work rendering; deliberately has no LLM dependency."""

import json
import shutil
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

from minicut.application import TimelineRenderer
from minicut.audio_denoise import build_denoiser_registry, resolve_denoiser
from minicut.cleanup_render import can_stream_cleanup, render_cleanup
from minicut.errors import ProcessingError, UserInputError
from minicut.export_settings import ExportSubtitleSettings
from minicut.media import StreamType
from minicut.output_plan import OutputPlan, validate_output_id
from minicut.output_repository import OutputCollectionRepository
from minicut.output_timeline import (
    OutputContextIssue,
    build_output_pages,
    coalesce_output_media,
    compile_output_timeline,
    inspect_output_context,
    map_output_words,
    validate_output_timeline,
)
from minicut.probe import ProbeResult, probe_media
from minicut.project import ProjectRepository
from minicut.render_command import (
    AudioFade,
    RenderCommandBuilder,
    SubtitleMode,
    VideoOutputMetadata,
)
from minicut.renderer import FfmpegRenderer
from minicut.semantic_segment import SemanticSegment
from minicut.subtitle import SubtitleCue, SubtitleLayoutPolicy, render_srt
from minicut.subtitle_ass import render_translated_ass
from minicut.subtitle_font import (
    SubtitleFont,
    resolve_selected_subtitle_font,
    resolve_subtitle_font,
)
from minicut.subtitle_layout import SubtitleGeometry
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
    export_id: str | None = None
    audio_fade_ms: int = 0
    denoiser_id: str = "none"
    plan_revision: int | None = None
    subtitle_settings: ExportSubtitleSettings | None = None


@dataclass(frozen=True, slots=True)
class OutputRenderResult:
    output_path: Path
    subtitle_path: Path
    record_path: Path
    timeline: Timeline
    context_issues: tuple[OutputContextIssue, ...]
    subtitle_warnings: tuple[str, ...] = ()


class RenderOutputUseCase:
    def __init__(
        self,
        *,
        renderer: TimelineRenderer | None = None,
        command_builder: RenderCommandBuilder | None = None,
        subtitle_font_resolver: Callable[[], SubtitleFont] = resolve_subtitle_font,
        media_probe: Callable[[Path], ProbeResult] = probe_media,
    ) -> None:
        self._renderer = renderer or FfmpegRenderer()
        self._builder = command_builder or RenderCommandBuilder()
        self._font_resolver = subtitle_font_resolver
        self._media_probe = media_probe

    def execute(self, request: OutputRenderRequest) -> OutputRenderResult:
        if request.timeout_seconds <= 0:
            raise UserInputError("Render timeout must be positive")
        fade = AudioFade(request.audio_fade_ms)
        denoiser = resolve_denoiser(request.denoiser_id, build_denoiser_registry())
        if request.export_id is not None:
            validate_output_id(request.export_id)
        repository = OutputCollectionRepository(
            request.project_directory, request.collection_id
        )
        with repository.mutation():
            collection = repository.read(request.segments)
            plan = repository.read_plan(
                collection, request.segments, request.output_id, request.plan_revision
            )
        if request.subtitle_settings is not None:
            plan = replace(plan, **request.subtitle_settings.plan_changes())
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
        font: SubtitleFont | None = None
        translation_font: SubtitleFont | None = None
        try:
            font = (
                resolve_selected_subtitle_font(plan.subtitle_style.source_font_id)
                if plan.subtitle_style and plan.subtitle_style.source_font_id
                else self._font_resolver()
            )
            translation_font = (
                resolve_selected_subtitle_font(plan.subtitle_style.translation_font_id)
                if plan.subtitle_style and plan.subtitle_style.translation_font_id
                else self._font_resolver()
                if plan.subtitle_style
                else font
            )
        except UserInputError:
            if request.subtitle_mode is SubtitleMode.BURNED:
                raise
        geometry = SubtitleGeometry.for_output(
            request.video_metadata.width,
            request.video_metadata.height,
            plan,
            font,
            translation_font,
        )
        pages = build_output_pages(
            timeline,
            plan,
            mapped,
            SubtitleLayoutPolicy(
                max_characters_per_line=12
                if request.video_metadata.width < request.video_metadata.height
                else 18
            ),
            portrait=request.video_metadata.width < request.video_metadata.height,
            geometry=geometry,
        )
        warning_times: dict[str, int] = {}
        for page in pages:
            for reason in page.review_reasons:
                warning_times.setdefault(reason, page.start_ms)
        subtitle_warnings = tuple(
            f"{time / 1000:.1f} 秒附近：{reason}"
            for reason, time in warning_times.items()
        )
        subtitle_text = render_srt(
            tuple(SubtitleCue(page.start_ms, page.end_ms, page.text) for page in pages),
            timeline.estimated_duration_ms,
        )
        destination_directory = (
            request.project_directory
            / "exports"
            / collection.collection_id
            / plan.output_id
        )
        output = destination_directory / f"v{plan.revision:04d}.mp4"
        if request.export_id is not None:
            destination_directory = destination_directory / request.export_id
            output = destination_directory / f"v{plan.revision:04d}.mp4"
        subtitle = output.with_suffix(".srt")
        record_path = repository.render_record_path(plan.output_id, plan.revision)
        if request.export_id is not None:
            record_path = record_path.parent / request.export_id / record_path.name
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
                media_timeline = coalesce_output_media(timeline, plan)
                stream_cleanup = can_stream_cleanup(plan, media_timeline)
                if stream_cleanup:
                    validate_output_timeline(
                        timeline,
                        plan,
                        request.segments,
                        collection.asset_id,
                        assets,
                        requirements,
                    )
                    render_cleanup(
                        media_timeline,
                        assets[0],
                        staged_video,
                        request.video_metadata,
                        fade,
                        None if denoiser is None else denoiser.ffmpeg_filter(),
                        requirements.require_audio,
                        self._builder,
                        self._renderer,
                        request.timeout_seconds,
                        request.cancellation,
                    )
                else:
                    command = self._builder.build_output_timeline(
                        timeline,
                        plan,
                        request.segments,
                        collection.asset_id,
                        assets,
                        str(staged_video),
                        requirements,
                        request.video_metadata,
                        audio_fade=fade,
                        denoise_filter=None
                        if denoiser is None
                        else denoiser.ffmpeg_filter(),
                    )
                    self._renderer.render_to_path(
                        command,
                        staged_video,
                        timeout_seconds=request.timeout_seconds,
                        cancellation=request.cancellation,
                    )
                staged_subtitle.write_text(subtitle_text, encoding="utf-8")
                styled_subtitles = request.subtitle_mode is SubtitleMode.BURNED
                subtitle_input = staged_subtitle
                fonts_directory: str | None = None
                if styled_subtitles:
                    subtitle_input = staged_video.with_suffix(".ass")
                    assert font is not None
                    subtitle_input.write_text(
                        render_translated_ass(
                            pages,
                            request.video_metadata.width,
                            request.video_metadata.height,
                            font,
                            plan,
                            translation_font=translation_font,
                        ),
                        encoding="utf-8",
                    )
                    if plan.subtitle_style:
                        fonts_path = Path(staging) / "fonts"
                        fonts_path.mkdir()
                        selected_paths = {font.path}
                        if translation_font:
                            selected_paths.add(translation_font.path)
                        for index, selected_path in enumerate(sorted(selected_paths)):
                            shutil.copyfile(
                                selected_path,
                                fonts_path / f"font-{index}{selected_path.suffix}",
                            )
                        fonts_directory = str(fonts_path)
                command = self._builder.build_subtitle_output(
                    str(staged_video),
                    str(subtitle_input),
                    str(staged_video),
                    request.subtitle_mode,
                    subtitle_font=font,
                    video_metadata=request.video_metadata,
                    styled_subtitles=styled_subtitles,
                    subtitle_fonts_directory=fonts_directory,
                    worker_threads=2 if stream_cleanup else None,
                )
                self._renderer.render_to_path(
                    command,
                    staged_video,
                    timeout_seconds=request.timeout_seconds,
                    cancellation=request.cancellation,
                )
                rendered_types = {
                    stream.stream_type
                    for stream in self._media_probe(staged_video).streams
                }
                if StreamType.VIDEO not in rendered_types or (
                    requirements.require_audio
                    and StreamType.AUDIO not in rendered_types
                ):
                    raise ProcessingError(
                        "渲染结果缺少必需的画面或音轨，未发布成片。请保留源素材并重试。"
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
                    "subtitle_translation_font": translation_font.to_record()
                    if translation_font
                    else None,
                    "video_metadata": asdict(request.video_metadata),
                    "audio_fade_ms": request.audio_fade_ms,
                    "denoiser_id": request.denoiser_id,
                    "context_issues": [asdict(issue) for issue in issues],
                    "subtitle_warnings": list(subtitle_warnings),
                },
                request.export_id,
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
            subtitle_warnings,
        )
