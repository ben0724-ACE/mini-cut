"""Application use cases orchestrating MiniCut domain services."""

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Protocol, cast

from minicut.deepseek_provider import create_deepseek_planner_from_env
from minicut.edit_plan import (
    EditAction,
    EditBrief,
    EditDecision,
    EditIntensity,
    EditPlan,
    ReasonCode,
    validate_edit_plan,
)
from minicut.errors import MiniCutError, ProcessingError, UserInputError
from minicut.importer import import_media
from minicut.media import MediaAsset, StreamType
from minicut.mlx_whisper import (
    MlxWhisperConfig,
    map_mlx_transcription,
    transcribe_with_mlx,
)
from minicut.open_source_whisper import (
    OpenSourceWhisperConfig,
    map_open_source_whisper_transcription,
    transcribe_with_open_source_whisper,
)
from minicut.project import ProjectManifest, ProjectRepository
from minicut.render_command import RenderCommandBuilder
from minicut.renderer import FfmpegRenderer
from minicut.rule_planner import RulePlanner
from minicut.segmentation import build_utterances
from minicut.semantic_segment import SemanticSegment
from minicut.semantic_segmentation import (
    build_rule_based_segments,
    mark_segment_candidates,
)
from minicut.subtitle import build_readable_cues, map_retained_words, render_srt
from minicut.text_normalization import normalize_transcript_words
from minicut.timeline import Timeline, compile_timeline
from minicut.timeline_validation import (
    TimelineTrackRequirements,
    validate_timeline_for_render,
)
from minicut.transcript import Transcript
from minicut.transcription_cache import (
    TranscriptCacheRepository,
    TranscriptionCacheKey,
    cache_key_for_mlx,
    cache_key_for_open_source_whisper,
)
from minicut.transcription_task import CancellationToken


@dataclass(frozen=True, slots=True)
class InitProjectRequest:
    """Validated input required to initialize a local project."""

    project_directory: Path
    project_id: str


@dataclass(frozen=True, slots=True)
class InitProjectResult:
    """User-facing identity of a newly initialized project."""

    project_directory: Path
    project_id: str


class InitProjectOperation(Protocol):
    """Callable application boundary used by the CLI."""

    def execute(self, request: InitProjectRequest) -> InitProjectResult: ...


class InitProjectUseCase:
    """Create the initial project manifest through the project repository."""

    def execute(self, request: InitProjectRequest) -> InitProjectResult:
        project_id = request.project_id.strip()
        if not project_id:
            raise UserInputError("Project ID must not be blank")
        repository = ProjectRepository(request.project_directory)
        repository.create(ProjectManifest(project_id=project_id))
        return InitProjectResult(request.project_directory.absolute(), project_id)


@dataclass(frozen=True, slots=True)
class TranscribeRequest:
    project_directory: Path
    source_path: Path
    provider: str
    model: str
    language: str


@dataclass(frozen=True, slots=True)
class TranscribeResult:
    transcript_id: str
    asset_id: str
    word_count: int
    reused: bool = False


class TranscribeOperation(Protocol):
    def execute(self, request: TranscribeRequest) -> TranscribeResult: ...


class AssetImporter(Protocol):
    def __call__(
        self, repository: ProjectRepository, source_path: str | Path
    ) -> MediaAsset: ...


class AssetTranscriber(Protocol):
    def __call__(self, asset: MediaAsset, request: TranscribeRequest) -> Transcript: ...


def _transcription_key(
    asset: MediaAsset, request: TranscribeRequest
) -> TranscriptionCacheKey:
    if request.provider == "mlx":
        config = MlxWhisperConfig(request.model, request.language)
        return cache_key_for_mlx(asset.content_fingerprint, config)
    if request.provider == "whisper":
        config = OpenSourceWhisperConfig(request.model, request.language)
        return cache_key_for_open_source_whisper(asset.content_fingerprint, config)
    raise UserInputError("Unsupported transcription provider")


def _transcribe_asset(asset: MediaAsset, request: TranscribeRequest) -> Transcript:
    if request.provider == "mlx":
        config = MlxWhisperConfig(request.model, request.language)
        response = transcribe_with_mlx(asset.source_path, config)
        return map_mlx_transcription(response, asset_id=asset.asset_id, config=config)
    if request.provider == "whisper":
        config = OpenSourceWhisperConfig(request.model, request.language)
        response = transcribe_with_open_source_whisper(asset.source_path, config)
        return map_open_source_whisper_transcription(
            response, asset_id=asset.asset_id, config=config
        )
    raise UserInputError("Unsupported transcription provider")


class TranscribeProjectUseCase:
    def __init__(
        self,
        *,
        importer: AssetImporter = import_media,
        transcriber: AssetTranscriber = _transcribe_asset,
    ) -> None:
        self._importer = importer
        self._transcriber = transcriber

    def execute(self, request: TranscribeRequest) -> TranscribeResult:
        repository = ProjectRepository(request.project_directory)
        repository.read()
        asset = self._importer(repository, request.source_path)
        cache = TranscriptCacheRepository(
            request.project_directory
            / ".minicut"
            / "transcripts"
            / f"{asset.asset_id}.json"
        )

        key = _transcription_key(asset, request)
        transcript = cache.read(key)
        reused = transcript is not None
        if transcript is None:
            transcript = self._transcriber(asset, request)
            cache.write(key, transcript)
        return TranscribeResult(
            transcript.transcript_id, asset.asset_id, len(transcript.words), reused
        )


@dataclass(frozen=True, slots=True)
class PlanRequest:
    project_directory: Path
    asset_id: str
    target_duration_ms: int
    intensity: EditIntensity
    style: str
    planner: str


@dataclass(frozen=True, slots=True)
class PlanResult:
    asset_id: str
    kept_segments: int
    deleted_segments: int
    artifact_path: Path
    reused: bool = False
    summary_path: Path | None = None


class PlanOperation(Protocol):
    def execute(self, request: PlanRequest) -> PlanResult: ...


class EditPlanner(Protocol):
    def __call__(
        self,
        request: PlanRequest,
        brief: EditBrief,
        segments: tuple[SemanticSegment, ...],
    ) -> EditPlan: ...


def _plan_edit(
    request: PlanRequest,
    brief: EditBrief,
    segments: tuple[SemanticSegment, ...],
) -> EditPlan:
    if request.planner == "rule":
        return RulePlanner().plan(brief, segments)
    if request.planner == "deepseek":
        return asyncio.run(create_deepseek_planner_from_env().plan(brief, segments))
    raise UserInputError("Unsupported edit planner")


def _read_cached_transcript(project_directory: Path, asset_id: str) -> Transcript:
    path = project_directory / ".minicut" / "transcripts" / f"{asset_id}.json"
    if not path.is_file():
        raise UserInputError("Transcript artifact does not exist")
    try:
        payload = cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))
        transcript_data = cast(dict[str, object], payload["transcript"])
        return Transcript.from_dict(transcript_data)
    except (KeyError, OSError, TypeError, UnicodeError, ValueError) as error:
        raise UserInputError("Transcript artifact is invalid") from error


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}-",
            suffix=".tmp",
            delete=False,
        ) as output:
            json.dump(value, output, ensure_ascii=False)
            output.write("\n")
            temporary_path = Path(output.name)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}-",
            suffix=".tmp",
            delete=False,
        ) as output:
            output.write(content)
            temporary_path = Path(output.name)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


class PlanProjectUseCase:
    def __init__(self, *, planner: EditPlanner = _plan_edit) -> None:
        self._planner = planner

    def execute(self, request: PlanRequest) -> PlanResult:
        if request.target_duration_ms <= 0:
            raise UserInputError("Target duration must be positive")
        if not request.asset_id.strip() or not request.style.strip():
            raise UserInputError("Asset ID and style must not be blank")
        ProjectRepository(request.project_directory).read()
        artifact_path = (
            request.project_directory
            / ".minicut"
            / "plans"
            / f"{request.asset_id}.json"
        )
        summary_path = (
            request.project_directory / ".minicut" / "plans" / f"{request.asset_id}.txt"
        )
        if artifact_path.is_file():
            existing_plan, existing_segments = _read_plan_artifact(
                request.project_directory, request.asset_id
            )
            expected_planner = (
                "llm" if request.planner == "deepseek" else request.planner
            )
            brief = existing_plan.brief
            if (
                brief.target_duration_ms == request.target_duration_ms
                and brief.intensity == request.intensity
                and brief.style == request.style
                and existing_plan.provenance.planner.value == expected_planner
            ):
                kept = sum(
                    decision.action.value == "keep"
                    for decision in existing_plan.decisions
                )
                if not summary_path.is_file():
                    _write_text(
                        summary_path,
                        _render_plan_summary(
                            request.asset_id, existing_plan, existing_segments
                        ),
                    )
                return PlanResult(
                    request.asset_id,
                    kept,
                    len(existing_plan.decisions) - kept,
                    artifact_path,
                    True,
                    summary_path,
                )
        transcript = _read_cached_transcript(
            request.project_directory, request.asset_id
        )
        mappings = normalize_transcript_words(transcript)
        utterances = transcript.utterances or build_utterances(transcript, mappings)
        segments = mark_segment_candidates(
            build_rule_based_segments(transcript, utterances)
        )
        brief = EditBrief(
            request.target_duration_ms,
            request.intensity,
            request.style,
            language=transcript.language,
        )
        plan = self._planner(request, brief, segments)
        _write_json(
            artifact_path,
            {
                "revision": 1,
                "asset_id": request.asset_id,
                "segments": [segment.to_dict() for segment in segments],
                "plan": plan.to_dict(),
            },
        )
        _write_text(
            summary_path, _render_plan_summary(request.asset_id, plan, segments)
        )
        kept = sum(decision.action.value == "keep" for decision in plan.decisions)
        return PlanResult(
            request.asset_id,
            kept,
            len(plan.decisions) - kept,
            artifact_path,
            False,
            summary_path,
        )


def _render_plan_summary(
    asset_id: str,
    plan: EditPlan,
    segments: tuple[SemanticSegment, ...],
) -> str:
    segments_by_id = {segment.segment_id: segment for segment in segments}
    kept = sum(decision.action.value == "keep" for decision in plan.decisions)
    lines = [
        f"MiniCut plan for asset {asset_id}",
        f"Summary: {plan.summary}",
        f"Target: {plan.brief.target_duration_ms} ms",
        f"Style: {plan.brief.style}",
        f"Decisions: {kept} keep, {len(plan.decisions) - kept} delete",
        "",
    ]
    for decision in plan.decisions:
        segment = segments_by_id[decision.segment_id]
        lines.extend(
            (
                f"[{decision.action.value.upper()}] {decision.segment_id} "
                f"({segment.start_ms}-{segment.end_ms} ms)",
                f"Text: {segment.text}",
                f"Reason: {decision.reason.value} — {decision.explanation}",
                "",
            )
        )
    return "\n".join(lines).rstrip() + "\n"


@dataclass(frozen=True, slots=True)
class ModifyPlanRequest:
    project_directory: Path
    asset_id: str
    restore_segment_ids: tuple[str, ...] = ()
    delete_segment_ids: tuple[str, ...] = ()
    output_path: Path | None = None
    timeout_seconds: float = 600


@dataclass(frozen=True, slots=True)
class ModifyPlanResult:
    asset_id: str
    kept_segments: int
    deleted_segments: int
    artifact_path: Path
    summary_path: Path
    revision: int = 1
    history_paths: tuple[Path, ...] = ()
    output_path: Path | None = None
    duration_ms: int | None = None


class ModifyPlanOperation(Protocol):
    def execute(self, request: ModifyPlanRequest) -> ModifyPlanResult: ...


class ModifyPlanUseCase:
    def __init__(self, *, render: "RenderOperation | None" = None) -> None:
        self._render = render or RenderProjectUseCase()

    def execute(self, request: ModifyPlanRequest) -> ModifyPlanResult:
        restore_ids = request.restore_segment_ids
        delete_ids = request.delete_segment_ids
        if not restore_ids and not delete_ids:
            raise UserInputError("At least one Segment must be restored or deleted")
        if len(set(restore_ids)) != len(restore_ids) or len(set(delete_ids)) != len(
            delete_ids
        ):
            raise UserInputError("Segment modifications must not contain duplicates")
        if set(restore_ids) & set(delete_ids):
            raise UserInputError("A Segment cannot be restored and deleted together")
        if request.timeout_seconds <= 0:
            raise UserInputError("Render timeout must be positive")
        ProjectRepository(request.project_directory).read()
        plan, segments = _read_plan_artifact(
            request.project_directory, request.asset_id
        )
        known_ids = {segment.segment_id for segment in segments}
        if (set(restore_ids) | set(delete_ids)) - known_ids:
            raise UserInputError("Plan modification references an unknown Segment ID")
        restore_set = set(restore_ids)
        delete_set = set(delete_ids)
        decisions = tuple(
            (
                EditDecision(
                    decision.segment_id,
                    EditAction.KEEP,
                    ReasonCode.USER_REQUIRED,
                    1.0,
                    "Restored by user.",
                    tuple(dict.fromkeys((*decision.labels, "user_override"))),
                )
                if decision.segment_id in restore_set
                else EditDecision(
                    decision.segment_id,
                    EditAction.DELETE,
                    ReasonCode.USER_REMOVED,
                    1.0,
                    "Deleted by user.",
                    tuple(dict.fromkeys((*decision.labels, "user_override"))),
                )
                if decision.segment_id in delete_set
                else decision
            )
            for decision in plan.decisions
        )
        revised = replace(
            plan,
            decisions=decisions,
            summary=(
                f"User revised plan: {len(restore_ids)} restored, "
                f"{len(delete_ids)} deleted."
            ),
        )
        try:
            validate_edit_plan(revised, segments)
        except ValueError as error:
            raise UserInputError(f"Plan modification is invalid: {error}") from error
        artifact_path = (
            request.project_directory
            / ".minicut"
            / "plans"
            / f"{request.asset_id}.json"
        )
        summary_path = artifact_path.with_suffix(".txt")
        current_revision = _read_plan_revision(
            request.project_directory, request.asset_id
        )
        history_directory = (
            request.project_directory
            / ".minicut"
            / "plans"
            / f"{request.asset_id}-history"
        )
        original_payload = {
            "revision": current_revision,
            "asset_id": request.asset_id,
            "segments": [segment.to_dict() for segment in segments],
            "plan": plan.to_dict(),
        }
        original_history = history_directory / f"{current_revision:04d}.json"
        if not original_history.exists():
            _write_json(original_history, original_payload)
        changed = revised != plan
        revision = current_revision + 1 if changed else current_revision
        revised_payload = {
            "revision": revision,
            "asset_id": request.asset_id,
            "segments": [segment.to_dict() for segment in segments],
            "plan": revised.to_dict(),
        }
        if changed:
            _write_json(artifact_path, revised_payload)
        revised_history = history_directory / f"{revision:04d}.json"
        if not revised_history.exists():
            _write_json(revised_history, revised_payload)
        _write_text(
            summary_path, _render_plan_summary(request.asset_id, revised, segments)
        )
        kept = sum(decision.action is EditAction.KEEP for decision in decisions)
        rendered = None
        if request.output_path is not None:
            rendered = self._render.execute(
                RenderRequest(
                    request.project_directory,
                    request.asset_id,
                    request.output_path,
                    request.timeout_seconds,
                )
            )
        return ModifyPlanResult(
            request.asset_id,
            kept,
            len(decisions) - kept,
            artifact_path,
            summary_path,
            revision,
            tuple(sorted(history_directory.glob("*.json"))),
            None if rendered is None else rendered.output_path,
            None if rendered is None else rendered.duration_ms,
        )


@dataclass(frozen=True, slots=True)
class RenderRequest:
    project_directory: Path
    asset_id: str
    output_path: Path
    timeout_seconds: float
    cancellation: CancellationToken | None = None


@dataclass(frozen=True, slots=True)
class RenderResult:
    output_path: Path
    subtitle_path: Path
    duration_ms: int
    reused: bool = False


class RenderOperation(Protocol):
    def execute(self, request: RenderRequest) -> RenderResult: ...


class TimelineRenderer(Protocol):
    def render_to_path(
        self,
        command: tuple[str, ...],
        output_path: str | Path,
        *,
        timeout_seconds: float,
        cancellation: CancellationToken | None = None,
    ) -> object: ...


def _read_plan_artifact(
    project_directory: Path, asset_id: str
) -> tuple[EditPlan, tuple[SemanticSegment, ...]]:
    path = project_directory / ".minicut" / "plans" / f"{asset_id}.json"
    return _read_plan_file(path, asset_id)


def _read_plan_file(
    path: Path, asset_id: str
) -> tuple[EditPlan, tuple[SemanticSegment, ...]]:
    if not path.is_file():
        raise UserInputError("Edit plan artifact does not exist")
    try:
        payload = cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))
        if payload["asset_id"] != asset_id:
            raise ValueError("asset mismatch")
        plan = EditPlan.from_dict(cast(dict[str, object], payload["plan"]))
        segment_data = cast(list[dict[str, object]], payload["segments"])
        return plan, tuple(SemanticSegment.from_dict(item) for item in segment_data)
    except (KeyError, OSError, TypeError, UnicodeError, ValueError) as error:
        raise UserInputError("Edit plan artifact is invalid") from error


@dataclass(frozen=True, slots=True)
class ReadPlanRequest:
    project_directory: Path
    asset_id: str
    revision: int | None = None


@dataclass(frozen=True, slots=True)
class ReadPlanResult:
    asset_id: str
    revision: int
    available_revisions: tuple[int, ...]
    plan: EditPlan
    segments: tuple[SemanticSegment, ...]


class ReadPlanOperation(Protocol):
    def execute(self, request: ReadPlanRequest) -> ReadPlanResult: ...


class ReadPlanUseCase:
    def execute(self, request: ReadPlanRequest) -> ReadPlanResult:
        ProjectRepository(request.project_directory).read()
        plans_directory = request.project_directory / ".minicut" / "plans"
        current_path = plans_directory / f"{request.asset_id}.json"
        current_revision = _read_plan_revision(
            request.project_directory, request.asset_id
        )
        history_directory = plans_directory / f"{request.asset_id}-history"
        available = tuple(
            sorted(
                int(path.stem)
                for path in history_directory.glob("*.json")
                if path.stem.isdigit()
            )
        )
        revision = current_revision if request.revision is None else request.revision
        if revision <= 0:
            raise UserInputError("Plan revision must be positive")
        if revision == current_revision:
            path = current_path
        else:
            path = history_directory / f"{revision:04d}.json"
        plan, segments = _read_plan_file(path, request.asset_id)
        revisions = tuple(sorted(set((*available, current_revision))))
        return ReadPlanResult(
            request.asset_id,
            revision,
            revisions,
            plan,
            segments,
        )


@dataclass(frozen=True, slots=True)
class PreviewTimelineRequest:
    project_directory: Path
    asset_id: str


@dataclass(frozen=True, slots=True)
class PreviewTimelineResult:
    asset_id: str
    plan_revision: int
    timeline: Timeline


class PreviewTimelineOperation(Protocol):
    def execute(self, request: PreviewTimelineRequest) -> PreviewTimelineResult: ...


class PreviewTimelineUseCase:
    """Compile the same deterministic timeline used by formal rendering."""

    def execute(self, request: PreviewTimelineRequest) -> PreviewTimelineResult:
        ProjectRepository(request.project_directory).read()
        plan, segments = _read_plan_artifact(
            request.project_directory, request.asset_id
        )
        timeline = compile_timeline(plan, segments, request.asset_id)
        revision = _read_plan_revision(request.project_directory, request.asset_id)
        return PreviewTimelineResult(request.asset_id, revision, timeline)


def _read_plan_revision(project_directory: Path, asset_id: str) -> int:
    path = project_directory / ".minicut" / "plans" / f"{asset_id}.json"
    try:
        payload = cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))
        revision = payload.get("revision", 1)
        if type(revision) is not int or revision <= 0:
            raise ValueError("invalid revision")
        return revision
    except (OSError, TypeError, UnicodeError, ValueError) as error:
        raise UserInputError("Edit plan artifact is invalid") from error


class RenderProjectUseCase:
    def __init__(
        self,
        *,
        command_builder: RenderCommandBuilder | None = None,
        renderer: TimelineRenderer | None = None,
    ) -> None:
        self._command_builder = command_builder or RenderCommandBuilder()
        self._renderer = renderer or FfmpegRenderer()

    def execute(self, request: RenderRequest) -> RenderResult:
        if request.timeout_seconds <= 0:
            raise UserInputError("Render timeout must be positive")
        manifest = ProjectRepository(request.project_directory).read()
        assets = tuple(
            asset for asset in manifest.assets if asset.asset_id == request.asset_id
        )
        if len(assets) != 1:
            raise UserInputError("Project asset does not exist")
        asset = assets[0]
        plan, segments = _read_plan_artifact(
            request.project_directory, request.asset_id
        )
        transcript = _read_cached_transcript(
            request.project_directory, request.asset_id
        )
        timeline = compile_timeline(plan, segments, request.asset_id)
        plan_revision = _read_plan_revision(request.project_directory, request.asset_id)
        subtitle_path = request.output_path.with_suffix(".srt")
        render_record_path = (
            request.project_directory
            / ".minicut"
            / "renders"
            / f"{request.asset_id}.json"
        )
        plan_path = (
            request.project_directory
            / ".minicut"
            / "plans"
            / f"{request.asset_id}.json"
        )
        if _can_reuse_render(
            render_record_path,
            plan_path,
            request.output_path,
            subtitle_path,
            timeline.estimated_duration_ms,
            plan_revision,
        ):
            return RenderResult(
                request.output_path.absolute(),
                subtitle_path.absolute(),
                timeline.estimated_duration_ms,
                True,
            )
        stream_types = {stream.stream_type for stream in asset.streams}
        requirements = TimelineTrackRequirements(
            require_audio=StreamType.AUDIO in stream_types,
            require_video=StreamType.VIDEO in stream_types,
        )
        validate_timeline_for_render(timeline, (asset,), requirements)
        if len(timeline.clips) == 1:
            command = self._command_builder.build_single_clip(
                timeline, (asset,), str(request.output_path)
            )
        else:
            command = self._command_builder.build_multi_clip(
                timeline,
                (asset,),
                str(request.output_path),
                requirements,
            )
        self._renderer.render_to_path(
            command,
            request.output_path,
            timeout_seconds=request.timeout_seconds,
            cancellation=request.cancellation,
        )
        mapped_words = map_retained_words(timeline, segments, transcript.words)
        cues = build_readable_cues(mapped_words, timeline.estimated_duration_ms)
        try:
            _write_text(
                subtitle_path,
                render_srt(cues, timeline.estimated_duration_ms),
            )
        except OSError as error:
            raise ProcessingError("Subtitle output could not be written") from error
        _write_json(
            render_record_path,
            {
                "asset_id": request.asset_id,
                "output_path": str(request.output_path.absolute()),
                "subtitle_path": str(subtitle_path.absolute()),
                "duration_ms": timeline.estimated_duration_ms,
                "plan_revision": plan_revision,
            },
        )
        return RenderResult(
            request.output_path.absolute(),
            subtitle_path.absolute(),
            timeline.estimated_duration_ms,
        )


def _can_reuse_render(
    record_path: Path,
    plan_path: Path,
    output_path: Path,
    subtitle_path: Path,
    duration_ms: int,
    plan_revision: int,
) -> bool:
    if (
        not record_path.is_file()
        or not output_path.is_file()
        or not subtitle_path.is_file()
    ):
        return False
    try:
        record = cast(
            dict[str, object], json.loads(record_path.read_text(encoding="utf-8"))
        )
        return (
            record["output_path"] == str(output_path.absolute())
            and record["subtitle_path"] == str(subtitle_path.absolute())
            and record["duration_ms"] == duration_ms
            and record.get("plan_revision") == plan_revision
            and record_path.stat().st_mtime_ns >= plan_path.stat().st_mtime_ns
        )
    except (KeyError, OSError, TypeError, UnicodeError, ValueError):
        return False


@dataclass(frozen=True, slots=True)
class EditRequest:
    project_directory: Path
    source_path: Path
    provider: str
    model: str
    language: str
    target_duration_ms: int
    intensity: EditIntensity
    style: str
    planner: str
    output_path: Path
    timeout_seconds: float
    on_progress: "EditProgressReporter" = lambda event: None
    cancellation: CancellationToken | None = None


@dataclass(frozen=True, slots=True)
class EditProgressEvent:
    stage: str
    status: str
    reused: bool = False
    estimated_duration_ms: int | None = None


EditProgressReporter = Callable[[EditProgressEvent], None]


class EditCancelled(ProcessingError):
    """Raised when the one-command workflow observes cancellation."""


@dataclass(frozen=True, slots=True)
class EditResult:
    asset_id: str
    output_path: Path
    subtitle_path: Path
    duration_ms: int
    reused_stages: tuple[str, ...]


class EditOperation(Protocol):
    def execute(self, request: EditRequest) -> EditResult: ...


class EditProjectUseCase:
    def __init__(
        self,
        *,
        transcribe: TranscribeOperation | None = None,
        plan: PlanOperation | None = None,
        render: RenderOperation | None = None,
    ) -> None:
        self._transcribe = transcribe or TranscribeProjectUseCase()
        self._plan = plan or PlanProjectUseCase()
        self._render = render or RenderProjectUseCase()

    def execute(self, request: EditRequest) -> EditResult:
        def check_cancelled(stage: str) -> None:
            if request.cancellation is not None and request.cancellation.is_cancelled:
                request.on_progress(EditProgressEvent(stage, "cancelled"))
                raise EditCancelled("Edit workflow was cancelled")

        request.on_progress(EditProgressEvent("transcribe", "running"))
        check_cancelled("transcribe")
        try:
            transcribed = self._transcribe.execute(
                TranscribeRequest(
                    request.project_directory,
                    request.source_path,
                    request.provider,
                    request.model,
                    request.language,
                )
            )
            check_cancelled("transcribe")
        except EditCancelled:
            raise
        except MiniCutError as error:
            if request.cancellation is not None and request.cancellation.is_cancelled:
                request.on_progress(EditProgressEvent("transcribe", "cancelled"))
                raise EditCancelled("Edit workflow was cancelled") from error
            request.on_progress(EditProgressEvent("transcribe", "failed"))
            raise
        request.on_progress(
            EditProgressEvent("transcribe", "succeeded", transcribed.reused)
        )
        request.on_progress(EditProgressEvent("plan", "running"))
        check_cancelled("plan")
        try:
            planned = self._plan.execute(
                PlanRequest(
                    request.project_directory,
                    transcribed.asset_id,
                    request.target_duration_ms,
                    request.intensity,
                    request.style,
                    request.planner,
                )
            )
            check_cancelled("plan")
        except EditCancelled:
            raise
        except MiniCutError as error:
            if request.cancellation is not None and request.cancellation.is_cancelled:
                request.on_progress(EditProgressEvent("plan", "cancelled"))
                raise EditCancelled("Edit workflow was cancelled") from error
            request.on_progress(EditProgressEvent("plan", "failed"))
            raise
        request.on_progress(EditProgressEvent("plan", "succeeded", planned.reused))
        request.on_progress(EditProgressEvent("render", "running"))
        check_cancelled("render")
        try:
            rendered = self._render.execute(
                RenderRequest(
                    request.project_directory,
                    transcribed.asset_id,
                    request.output_path,
                    request.timeout_seconds,
                    request.cancellation,
                )
            )
            check_cancelled("render")
        except EditCancelled:
            raise
        except MiniCutError as error:
            if request.cancellation is not None and request.cancellation.is_cancelled:
                request.on_progress(EditProgressEvent("render", "cancelled"))
                raise EditCancelled("Edit workflow was cancelled") from error
            request.on_progress(EditProgressEvent("render", "failed"))
            raise
        request.on_progress(
            EditProgressEvent(
                "render",
                "succeeded",
                rendered.reused,
                rendered.duration_ms,
            )
        )
        reused = tuple(
            stage
            for stage, was_reused in (
                ("transcribe", transcribed.reused),
                ("plan", planned.reused),
                ("render", rendered.reused),
            )
            if was_reused
        )
        return EditResult(
            transcribed.asset_id,
            rendered.output_path,
            rendered.subtitle_path,
            rendered.duration_ms,
            reused,
        )


@dataclass(frozen=True, slots=True)
class InspectRequest:
    project_directory: Path
    asset_id: str | None = None


@dataclass(frozen=True, slots=True)
class InspectedAsset:
    asset_id: str
    source_path: str
    duration_ms: int
    has_transcript: bool
    transcript_word_count: int | None
    has_plan: bool
    kept_segments: int | None
    deleted_segments: int | None

    def to_dict(self) -> dict[str, object]:
        return {
            "asset_id": self.asset_id,
            "source_path": self.source_path,
            "duration_ms": self.duration_ms,
            "has_transcript": self.has_transcript,
            "transcript_word_count": self.transcript_word_count,
            "has_plan": self.has_plan,
            "kept_segments": self.kept_segments,
            "deleted_segments": self.deleted_segments,
        }


@dataclass(frozen=True, slots=True)
class InspectResult:
    project_id: str
    asset_ids: tuple[str, ...]
    selected_asset: InspectedAsset | None

    def to_dict(self) -> dict[str, object]:
        return {
            "project_id": self.project_id,
            "asset_count": len(self.asset_ids),
            "asset_ids": list(self.asset_ids),
            "selected_asset": (
                None if self.selected_asset is None else self.selected_asset.to_dict()
            ),
        }


class InspectOperation(Protocol):
    def execute(self, request: InspectRequest) -> InspectResult: ...


class InspectProjectUseCase:
    def execute(self, request: InspectRequest) -> InspectResult:
        manifest = ProjectRepository(request.project_directory).read()
        asset_ids = tuple(asset.asset_id for asset in manifest.assets)
        if request.asset_id is None:
            return InspectResult(manifest.project_id, asset_ids, None)
        assets = tuple(
            asset for asset in manifest.assets if asset.asset_id == request.asset_id
        )
        if len(assets) != 1:
            raise UserInputError("Project asset does not exist")
        asset = assets[0]
        transcript_path = (
            request.project_directory
            / ".minicut"
            / "transcripts"
            / f"{asset.asset_id}.json"
        )
        transcript = (
            _read_cached_transcript(request.project_directory, asset.asset_id)
            if transcript_path.is_file()
            else None
        )
        plan_path = (
            request.project_directory / ".minicut" / "plans" / f"{asset.asset_id}.json"
        )
        plan = (
            _read_plan_artifact(request.project_directory, asset.asset_id)[0]
            if plan_path.is_file()
            else None
        )
        kept_segments = None
        deleted_segments = None
        if plan is not None:
            kept_segments = sum(
                decision.action.value == "keep" for decision in plan.decisions
            )
            deleted_segments = len(plan.decisions) - kept_segments
        selected = InspectedAsset(
            asset.asset_id,
            asset.source_path,
            asset.duration_ms,
            transcript is not None,
            None if transcript is None else len(transcript.words),
            plan is not None,
            kept_segments,
            deleted_segments,
        )
        return InspectResult(manifest.project_id, asset_ids, selected)


__all__ = [
    "EditCancelled",
    "EditOperation",
    "EditProgressEvent",
    "EditProgressReporter",
    "EditProjectUseCase",
    "EditRequest",
    "EditResult",
    "InspectOperation",
    "InspectProjectUseCase",
    "InspectRequest",
    "InspectResult",
    "InspectedAsset",
    "ModifyPlanOperation",
    "ModifyPlanRequest",
    "ModifyPlanResult",
    "ModifyPlanUseCase",
    "InitProjectOperation",
    "InitProjectRequest",
    "InitProjectResult",
    "InitProjectUseCase",
    "PlanOperation",
    "PlanProjectUseCase",
    "PlanRequest",
    "PlanResult",
    "PreviewTimelineOperation",
    "PreviewTimelineRequest",
    "PreviewTimelineResult",
    "PreviewTimelineUseCase",
    "ReadPlanOperation",
    "ReadPlanRequest",
    "ReadPlanResult",
    "ReadPlanUseCase",
    "RenderOperation",
    "RenderProjectUseCase",
    "RenderRequest",
    "RenderResult",
    "TranscribeOperation",
    "TranscribeProjectUseCase",
    "TranscribeRequest",
    "TranscribeResult",
]
