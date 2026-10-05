"""Local HTTP API that adapts web schemas to MiniCut application services."""

import asyncio
import json
import mimetypes
import os
import shutil
from collections.abc import AsyncGenerator, Callable, Iterator
from concurrent.futures import CancelledError, Future
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock
from time import monotonic
from typing import Annotated, Self, cast
from uuid import uuid4

import uvicorn
from fastapi import (
    BackgroundTasks,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    status,
)
from pydantic import BaseModel, Field, StringConstraints, model_validator
from starlette.concurrency import run_in_threadpool
from starlette.responses import StreamingResponse

from minicut.application import (
    InitProjectOperation,
    InitProjectRequest,
    InitProjectUseCase,
    InspectOperation,
    InspectProjectUseCase,
    InspectRequest,
    InspectResult,
    ModifyPlanOperation,
    ModifyPlanRequest,
    ModifyPlanUseCase,
    PlanOperation,
    PlanProjectUseCase,
    PlanRequest,
    PreviewTimelineOperation,
    PreviewTimelineRequest,
    PreviewTimelineUseCase,
    ReadPlanOperation,
    ReadPlanRequest,
    ReadPlanResult,
    ReadPlanUseCase,
    RenderOperation,
    RenderProjectUseCase,
    RenderRequest,
    TranscribeOperation,
    TranscribeProjectUseCase,
    TranscribeRequest,
)
from minicut.cover_api import cover_router
from minicut.cover_design import CoverDesign, CoverStore
from minicut.edit_plan import EditIntensity
from minicut.errors import MiniCutError, UserInputError
from minicut.export_settings import ExportSubtitleSettings, PreviewOptions
from minicut.export_settings_api import export_settings_router
from minicut.generation_presets import (
    GenerationPresetBody,
    GenerationPresetLibrary,
    PresetNameConflict,
    PresetNotFound,
    PresetRenameBody,
)
from minicut.generation_settings import GenerationDraft, GenerationSettings
from minicut.highlight_brief import HighlightBrief, HighlightPreset
from minicut.highlight_service import (
    RevisionConflict,
    edit_output_item,
    generate_highlights,
    output_versions,
    read_highlights,
    reorder_output,
    save_output_ranges,
    save_output_subtitle_settings,
    translate_output_subtitles,
)
from minicut.importer import import_media
from minicut.llm_provider import TextModelProviderError
from minicut.media import classify_media
from minicut.output_export import RENDER_ENGINE_VERSION, export_output, preview_output
from minicut.output_repository import OutputCollectionRepository
from minicut.platform_support import (
    default_transcription_model,
    default_transcription_provider,
    process_alive,
    supports_mlx,
    valid_windows_filename,
)
from minicut.project import ProjectRepository
from minicut.project_deletion import ProjectDeletionGuard
from minicut.render_profile import RenderProfile
from minicut.subtitle_font import available_subtitle_fonts
from minicut.subtitle_style import SubtitleStyle
from minicut.task_workers import TaskQueueFull, TaskWorkerPool, wait_for_task
from minicut.transcription_task import CancellationToken, TranscriptionCancelled
from minicut.workflows import JsonObject, workflow_router

ProjectId = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")]
SafeFileName = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")]

_DEFAULT_EXPORT_CONCURRENCY = 2
_MAX_EXPORT_CONCURRENCY = 4


def _resolve_export_concurrency(configured: int | None) -> int:
    value: object = (
        os.environ.get("MINICUT_EXPORT_CONCURRENCY", _DEFAULT_EXPORT_CONCURRENCY)
        if configured is None
        else configured
    )
    if isinstance(value, bool):
        raise ValueError("MINICUT_EXPORT_CONCURRENCY must be an integer from 1 to 4")
    try:
        concurrency = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        raise ValueError(
            "MINICUT_EXPORT_CONCURRENCY must be an integer from 1 to 4"
        ) from error
    if not 1 <= concurrency <= _MAX_EXPORT_CONCURRENCY:
        raise ValueError("MINICUT_EXPORT_CONCURRENCY must be an integer from 1 to 4")
    return concurrency


class ProjectCreateBody(BaseModel):
    """HTTP input for creating one project below the configured root."""

    project_id: ProjectId | None = None
    name: (
        Annotated[
            str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
        ]
        | None
    ) = None

    @model_validator(mode="after")
    def require_identity(self) -> Self:
        if self.project_id is None and self.name is None:
            raise ValueError("Project name or ID is required")
        return self


class ProjectSummaryResponse(BaseModel):
    """Stable web representation of one local project."""

    project_id: str
    asset_count: int
    name: str | None = None


class ProjectDetailResponse(ProjectSummaryResponse):
    """Project summary with identifiers needed for subsequent API calls."""

    asset_ids: list[str]


class TranscribeTaskBody(BaseModel):
    source_path: str | None = None
    asset_id: SafeFileName | None = None
    provider: str = Field(pattern=r"^(mlx|whisper)$")
    model: str
    language: str = "zh"

    @model_validator(mode="after")
    def require_source(self) -> Self:
        if (self.source_path is None) == (self.asset_id is None):
            raise ValueError("Provide exactly one source path or asset ID")
        return self


class PlanTaskBody(BaseModel):
    asset_id: str
    target_duration_ms: int = Field(gt=0)
    intensity: EditIntensity = EditIntensity.BALANCED
    style: str = "concise"
    planner: str = Field(default="rule", pattern=r"^(rule|deepseek)$")


class HighlightTaskBody(BaseModel):
    asset_id: SafeFileName
    preset: HighlightPreset
    cleanup_version: int | None = Field(default=2, ge=1, le=2)
    boundary_version: int | None = Field(default=3, ge=2, le=3)
    custom_preset_id: str | None = Field(default=None, max_length=80)
    custom_preset_name: str | None = Field(default=None, max_length=80)
    body_mode: str = Field(default="continuous", pattern=r"^(continuous|compact)$")
    translation_language: str | None = Field(default=None, pattern=r"^(zh|en)$")
    subtitle_mode: str = Field(default="bilingual", pattern=r"^(bilingual|translated)$")
    count: int = Field(ge=1, le=10)
    min_ms: int | None = Field(default=None, gt=0)
    max_ms: int | None = Field(default=None, gt=0)
    hook_ms: int | None = Field(default=None, ge=1000, le=60000)
    instructions: str = Field(default="", max_length=12000)
    preset_prompt: str | None = Field(default=None, min_length=1, max_length=12000)
    editing_prompt: str | None = Field(default=None, min_length=1, max_length=25000)
    max_source_overlap: float = Field(default=0.3, ge=0, le=1)

    def brief(self) -> HighlightBrief:
        values = self.model_dump(
            exclude={"asset_id", "custom_preset_id", "custom_preset_name"}
        )
        if self.preset is HighlightPreset.CLEAN_SPEECH and self.cleanup_version:
            values.update(
                count=1,
                min_ms=None,
                max_ms=None,
                hook_ms=None,
                body_mode="compact",
                max_source_overlap=1,
                boundary_version=None,
            )
        else:
            values["cleanup_version"] = None
        return HighlightBrief(**values)

    @model_validator(mode="after")
    def valid_brief(self) -> Self:
        self.brief()
        return self


class OutputTitleBody(BaseModel):
    base_revision: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=200)


class ManualSplitBody(BaseModel):
    base_revision: int = Field(ge=1)
    lines: list[str] = Field(min_length=2, max_length=100)
    apply: bool = False

    @model_validator(mode="after")
    def validate_size(self) -> Self:
        if sum(len(line) for line in self.lines) > 12000:
            raise ValueError("分句文本过长")
        return self


class HighlightSelectionBody(BaseModel):
    output_ids: list[str]


class OutputItemEditBody(BaseModel):
    source_start_ms: int | None = Field(default=None, ge=0, strict=True)
    source_end_ms: int | None = Field(default=None, gt=0, strict=True)
    deleted: bool | None = None
    display_text: str | None = Field(default=None, min_length=1, max_length=12000)
    translation_text: str | None = Field(default=None, min_length=1, max_length=12000)
    subtitle_mode: str | None = Field(default=None, pattern=r"^(bilingual|translated)$")

    @model_validator(mode="after")
    def require_change(self) -> Self:
        if (self.source_start_ms is None) != (self.source_end_ms is None):
            raise ValueError("Both source boundaries are required")
        if (
            self.deleted is None
            and self.display_text is None
            and self.translation_text is None
            and self.subtitle_mode is None
            and self.source_start_ms is None
        ):
            raise ValueError("Provide a subtitle or decision change")
        return self


class OutputRangeBody(BaseModel):
    instance_id: str
    source_start_ms: int = Field(ge=0, strict=True)
    source_end_ms: int = Field(gt=0, strict=True)


class OutputRangesBody(BaseModel):
    base_revision: int = Field(ge=1, strict=True)
    ranges: list[OutputRangeBody] = Field(min_length=1)


class OutputOrderBody(BaseModel):
    order: list[str]
    roles: dict[str, str] = Field(default_factory=dict)
    hook_transition_ms: int | None = Field(default=None, ge=0, le=1000, strict=True)
    hook_transition_kind: str | None = Field(
        default=None, pattern=r"^(fade|tv_static)$"
    )


class OutputSubtitleSettingsBody(BaseModel):
    base_revision: int = Field(ge=1, strict=True)
    subtitle_mode: str | None = Field(
        default=None, pattern=r"^(bilingual|translated|source)$"
    )
    subtitle_source_scale: float = Field(ge=0.7, le=1.5)
    subtitle_translation_scale: float = Field(ge=0.7, le=1.5)
    subtitle_horizontal_percent: int = Field(ge=20, le=80, strict=True)
    subtitle_bottom_percent: int = Field(ge=5, le=40, strict=True)
    subtitle_order: str = Field(pattern=r"^(source_first|translation_first)$")
    subtitle_style: SubtitleStyle | None = None

    @model_validator(mode="before")
    @classmethod
    def legacy_shared_subtitle_font(cls, value: object) -> object:
        if isinstance(value, dict):
            data = cast(dict[str, object], value)
            style = data.get("subtitle_style")
            if isinstance(style, dict) and "font_id" in style:
                normalized = dict(cast(dict[str, object], style))
                shared = normalized.pop("font_id")
                normalized.setdefault("source_font_id", shared)
                normalized.setdefault("translation_font_id", shared)
                return {**data, "subtitle_style": normalized}
        return cast(object, value)


class OutputTranslationBody(BaseModel):
    collection_id: SafeFileName
    output_id: SafeFileName
    base_revision: int = Field(ge=1, strict=True)
    language: str = Field(pattern=r"^(zh|en)$")


class RenderTaskBody(BaseModel):
    asset_id: str
    output_name: SafeFileName
    timeout_seconds: float = Field(default=600, gt=0)


class OutputPreviewBody(PreviewOptions):
    collection_id: SafeFileName
    output_id: SafeFileName
    revision: int = Field(ge=1)


class OutputPreviewQuery(PreviewOptions):
    @model_validator(mode="before")
    @classmethod
    def parse_subtitle_query(cls, value: object) -> object:
        if isinstance(value, dict):
            data = cast(dict[str, object], value)
            raw = data.get("subtitle_settings")
            if isinstance(raw, str):
                return {**data, "subtitle_settings": json.loads(raw) if raw else None}
        return cast(object, value)

    revision: int = Field(ge=1)

    @model_validator(mode="before")
    @classmethod
    def parse_query_integers(cls, value: object) -> object:
        # URL parameters arrive as strings; retain the strict JSON body schema.
        if isinstance(value, dict):
            parsed = cast(dict[str, object], value).copy()
            for key in ("resolution", "audio_fade_ms"):
                raw = parsed.get(key)
                if isinstance(raw, str):
                    try:
                        parsed[key] = int(raw)
                    except ValueError:
                        pass
            return parsed
        return value


class OutputExportBody(BaseModel):
    subtitle_settings: ExportSubtitleSettings | None = None
    cover_version: int | None = Field(default=None, ge=0)
    cover_snapshot: CoverDesign | None = None
    collection_id: SafeFileName
    output_id: SafeFileName
    revision: int = Field(ge=1)
    subtitle_mode: str = Field(default="soft", pattern=r"^(soft|burned)$")
    audio_fade_ms: int = Field(default=0, ge=0, le=500)
    denoiser_id: str = Field(default="none", pattern=r"^(none|afftdn)$")
    aspect_ratio: str = Field(
        default="original", pattern=r"^(original|16:9|9:16|1:1|4:5)$"
    )
    resolution: int = 1080
    fit: str = Field(default="pad", pattern=r"^(pad|crop)$")
    crop_left: float = Field(default=0, ge=0, le=95)
    crop_right: float = Field(default=0, ge=0, le=95)
    crop_top: float = Field(default=0, ge=0, le=95)
    crop_bottom: float = Field(default=0, ge=0, le=95)

    @model_validator(mode="after")
    def validate_profile(self) -> Self:
        RenderProfile(
            self.aspect_ratio,
            self.resolution,
            self.fit,
            self.crop_left,
            self.crop_right,
            self.crop_top,
            self.crop_bottom,
        )
        return self


class OutputExportBatchBody(BaseModel):
    outputs: list[OutputExportBody] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def unique_outputs(self) -> Self:
        ids = [(output.collection_id, output.output_id) for output in self.outputs]
        if (
            len(set(ids)) != len(ids)
            or len({output.collection_id for output in self.outputs}) != 1
        ):
            raise ValueError("Select distinct outputs from one collection")
        return self


class TaskResponse(BaseModel):
    task_id: str
    kind: str
    status: str
    result: dict[str, object] | None = None
    error: str | None = None
    progress: dict[str, object] | None = None
    resumable: bool = False
    configuration: dict[str, str] | None = None


class PlanSegmentResponse(BaseModel):
    segment_id: str
    text: str
    start_ms: int
    end_ms: int
    action: str
    reason: str
    confidence: float
    explanation: str


class PlanDetailResponse(BaseModel):
    asset_id: str
    revision: int
    available_revisions: list[int]
    summary: str
    target_duration_ms: int
    intensity: str
    style: str
    segments: list[PlanSegmentResponse]


class ModifyPlanBody(BaseModel):
    restore_segment_ids: list[str] = Field(default_factory=list)
    delete_segment_ids: list[str] = Field(default_factory=list)
    output_name: SafeFileName | None = None
    timeout_seconds: float = Field(default=600, gt=0)


class PlanVersionsResponse(BaseModel):
    asset_id: str
    current_revision: int
    revisions: list[int]


class PreviewClipResponse(BaseModel):
    clip_id: str
    segment_ids: list[str]
    source_start_ms: int
    source_end_ms: int
    output_start_ms: int
    output_end_ms: int


class PreviewTimelineResponse(BaseModel):
    asset_id: str
    plan_revision: int
    estimated_duration_ms: int
    clips: list[PreviewClipResponse]
    jump_cut_risks: list["JumpCutRiskResponse"]


class JumpCutRiskResponse(BaseModel):
    left_clip_id: str
    right_clip_id: str
    removed_gap_ms: int
    output_at_ms: int
    explanation: str


def _job_path(project_directory: Path, task_id: str) -> Path:
    return project_directory / ".minicut" / "jobs" / f"{task_id}.json"


def _write_job(path: Path, payload: dict[str, object], *, create: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if create:
        output = path.open("x", encoding="utf-8")
        try:
            with output:
                json.dump(payload, output, ensure_ascii=False)
                output.write("\n")
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return
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
            json.dump(payload, output, ensure_ascii=False)
            output.write("\n")
            temporary_path = Path(output.name)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _read_job(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("job is not an object")
        job = cast(dict[str, object], value)
        if job.get("status") in ("running", "pending"):
            pid = job.get("owner_pid")
            alive = False
            if type(pid) is int and pid > 0:
                alive = process_alive(pid)
            if not alive:
                job.update(
                    status="failed",
                    error="服务已重启，任务已中断；可恢复已保存的阶段。",
                    resumable=True,
                )
        return job
    except (OSError, TypeError, UnicodeError, ValueError) as error:
        raise HTTPException(status_code=404, detail="Task does not exist") from error


def _task_response(payload: dict[str, object]) -> TaskResponse:
    if payload.get("kind") == "transcribe":
        request = cast(dict[str, object], payload.get("request", {}))
        payload = {
            **payload,
            "configuration": {
                key: request[key]
                for key in ("provider", "model", "language")
                if key in request
            },
        }
    return TaskResponse.model_validate(payload)


@dataclass
class _TaskRunner:
    run: Callable[[], None]
    fail_submission: Callable[[], None]
    pool: TaskWorkerPool
    settle: Callable[[Future[None]], None]
    identity: tuple[str, str]
    future: Future[None] | None = None


def _plan_response(result: ReadPlanResult) -> PlanDetailResponse:
    decisions = {decision.segment_id: decision for decision in result.plan.decisions}
    return PlanDetailResponse(
        asset_id=result.asset_id,
        revision=result.revision,
        available_revisions=list(result.available_revisions),
        summary=result.plan.summary,
        target_duration_ms=result.plan.brief.target_duration_ms,
        intensity=result.plan.brief.intensity.value,
        style=result.plan.brief.style,
        segments=[
            PlanSegmentResponse(
                segment_id=segment.segment_id,
                text=segment.text,
                start_ms=segment.start_ms,
                end_ms=segment.end_ms,
                action=decisions[segment.segment_id].action.value,
                reason=decisions[segment.segment_id].reason.value,
                confidence=decisions[segment.segment_id].confidence,
                explanation=decisions[segment.segment_id].explanation,
            )
            for segment in result.segments
        ],
    )


def _resolve_project_resource(project_directory: Path, relative_path: str) -> Path:
    """Resolve an export while preventing traversal and escaping symlinks."""
    exports_directory = (project_directory / "exports").resolve()
    candidate = (exports_directory / relative_path).resolve()
    if not candidate.is_relative_to(exports_directory):
        raise HTTPException(status_code=400, detail="Media path is not allowed")
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="Media does not exist")
    return candidate


def _parse_byte_range(value: str, size: int) -> tuple[int, int]:
    """Parse one HTTP byte range, including suffix ranges."""
    if not value.startswith("bytes=") or "," in value:
        raise ValueError("unsupported range")
    bounds = value.removeprefix("bytes=").split("-", maxsplit=1)
    if len(bounds) != 2 or (not bounds[0] and not bounds[1]):
        raise ValueError("invalid range")
    if not bounds[0]:
        length = int(bounds[1])
        if length <= 0:
            raise ValueError("invalid suffix")
        start = max(size - length, 0)
        return start, size - 1
    start = int(bounds[0])
    end = size - 1 if not bounds[1] else int(bounds[1])
    if start < 0 or start >= size or end < start:
        raise ValueError("unsatisfiable range")
    return start, min(end, size - 1)


def _stream_file(path: Path, range_header: str | None) -> StreamingResponse:
    size = path.stat().st_size
    start, end, response_status = 0, size - 1, status.HTTP_200_OK
    if range_header is not None:
        try:
            start, end = _parse_byte_range(range_header, size)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE,
                detail="Requested range is not satisfiable",
                headers={"Content-Range": f"bytes */{size}"},
            ) from None
        response_status = status.HTTP_206_PARTIAL_CONTENT

    def content() -> Iterator[bytes]:
        remaining = end - start + 1
        with path.open("rb") as source:
            source.seek(start)
            while remaining:
                chunk = source.read(min(64 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(end - start + 1),
    }
    if response_status == status.HTTP_206_PARTIAL_CONTENT:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return StreamingResponse(
        content(), status_code=response_status, headers=headers, media_type=media_type
    )


def create_app(
    projects_root: Path,
    *,
    export_concurrency: int | None = None,
    task_queue_capacity: int = 64,
    init_project: InitProjectOperation | None = None,
    inspect_project: InspectOperation | None = None,
    transcribe: TranscribeOperation | None = None,
    plan: PlanOperation | None = None,
    render: RenderOperation | None = None,
    read_plan: ReadPlanOperation | None = None,
    modify_plan: ModifyPlanOperation | None = None,
    preview_timeline: PreviewTimelineOperation | None = None,
    highlights: Callable[
        [Path, str, str, HighlightBrief], dict[str, object]
    ] = generate_highlights,
) -> FastAPI:
    """Create an API instance bound to one local projects directory."""
    root = projects_root.absolute()
    initializer = init_project or InitProjectUseCase()
    inspector = inspect_project or InspectProjectUseCase()
    transcriber = transcribe or TranscribeProjectUseCase()
    planner = plan or PlanProjectUseCase()
    renderer = render or RenderProjectUseCase()
    plan_reader = read_plan or ReadPlanUseCase()
    plan_modifier = modify_plan or ModifyPlanUseCase()
    preview_compiler = preview_timeline or PreviewTimelineUseCase()
    export_concurrency = _resolve_export_concurrency(export_concurrency)
    compute_workers = TaskWorkerPool(
        1, capacity=task_queue_capacity, name="minicut-compute"
    )
    export_workers = TaskWorkerPool(
        export_concurrency, capacity=task_queue_capacity, name="minicut-export"
    )
    workflow_workers = TaskWorkerPool(
        2, capacity=task_queue_capacity, name="minicut-workflow"
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
        try:
            yield
        finally:
            # Coordinators must finish their children before child queues close.
            for pool in (workflow_workers, compute_workers, export_workers):
                await asyncio.to_thread(pool.shutdown)

    api = FastAPI(title="MiniCut local API", version="0.1.0", lifespan=lifespan)

    api.add_middleware(ProjectDeletionGuard)
    preset_library = GenerationPresetLibrary(root)

    @api.get("/api/transcription-defaults")
    def transcription_defaults() -> dict[str, object]:  # pyright: ignore[reportUnusedFunction]
        return {
            "options": {
                "provider": default_transcription_provider(),
                "model": default_transcription_model(),
                "language": "zh",
            },
            "mlx_supported": supports_mlx(),
        }

    @api.get("/api/generation-presets")
    def list_generation_presets() -> list[dict[str, object]]:  # pyright: ignore[reportUnusedFunction]
        return preset_library.list()

    @api.post("/api/generation-presets", status_code=201)
    def create_generation_preset(body: GenerationPresetBody) -> dict[str, object]:  # pyright: ignore[reportUnusedFunction]
        try:
            return preset_library.create(body)
        except PresetNameConflict:
            raise HTTPException(409, "已有同名预设，请换一个名称") from None

    @api.put("/api/generation-presets/{preset_id}")
    def update_generation_preset(  # pyright: ignore[reportUnusedFunction]
        preset_id: SafeFileName, body: GenerationPresetBody
    ) -> dict[str, object]:
        try:
            return preset_library.update(preset_id, body)
        except PresetNameConflict:
            raise HTTPException(409, "已有同名预设，请换一个名称") from None
        except PresetNotFound:
            raise HTTPException(404, "预设已删除或不存在，请重新读取预设库") from None

    @api.patch("/api/generation-presets/{preset_id}")
    def rename_generation_preset(  # pyright: ignore[reportUnusedFunction]
        preset_id: SafeFileName, body: PresetRenameBody
    ) -> dict[str, object]:
        try:
            return preset_library.rename(preset_id, body.name)
        except PresetNameConflict:
            raise HTTPException(409, "已有同名预设，请换一个名称") from None
        except PresetNotFound:
            raise HTTPException(404, "预设已删除或不存在，请重新读取预设库") from None

    @api.delete("/api/generation-presets/{preset_id}")
    def delete_generation_preset(preset_id: SafeFileName) -> dict[str, bool]:  # pyright: ignore[reportUnusedFunction]
        try:
            preset_library.delete(preset_id)
        except PresetNotFound:
            raise HTTPException(404, "预设已删除或不存在，请重新读取预设库") from None
        return {"deleted": True}

    def inspect(project_id: str) -> InspectResult:
        try:
            return inspector.execute(InspectRequest(root / project_id))
        except MiniCutError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    def read_plan_result(
        project_id: str, asset_id: str, revision: int | None = None
    ) -> ReadPlanResult:
        try:
            return plan_reader.execute(
                ReadPlanRequest(root / project_id, asset_id, revision)
            )
        except MiniCutError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    export_tokens: dict[tuple[str, str], CancellationToken] = {}
    task_futures: dict[tuple[str, str], tuple[TaskWorkerPool, Future[None]]] = {}
    resume_lock = Lock()

    def progress(project_id: str, task_id: str, done: int, total: int) -> None:
        path = _job_path(root / project_id, task_id)
        job = _read_job(path)
        job["progress"] = {"completed": done, "total": total, "phase": "transcription"}
        _write_job(path, job)

    def existing_task(
        path: Path, kind: str, request_data: dict[str, object]
    ) -> TaskResponse:
        existing = _read_job(path)
        if existing.get("kind") != kind or existing.get("request") != request_data:
            raise HTTPException(
                status_code=409,
                detail="Idempotency key is already used by another request",
            )
        return _task_response(existing)

    def submit_task(
        project_id: str,
        task_id: str,
        kind: str,
        request_data: dict[str, object],
        background_tasks: BackgroundTasks,
        operation: Callable[[], dict[str, object]],
        *,
        runners: list[_TaskRunner] | None = None,
        generation_config: dict[str, object] | None = None,
    ) -> TaskResponse:
        project_directory = root / project_id
        inspect(project_id)
        path = _job_path(project_directory, task_id)
        pending: dict[str, object] = {
            "task_id": task_id,
            "owner_pid": os.getpid(),
            "resumable": kind
            in ("transcribe", "highlights", "output-export", "output-preview"),
            "kind": kind,
            "status": "pending",
            "request": request_data,
            "result": None,
            "error": None,
        }
        if kind == "highlights":
            pending["created_at"] = datetime.now(UTC).isoformat()
            pending["generation_config"] = generation_config
        try:
            _write_job(path, pending, create=True)
        except FileExistsError:
            return existing_task(path, kind, request_data)

        token = export_tokens.setdefault((project_id, task_id), CancellationToken())

        def fail_submission() -> None:
            job = _read_job(path)
            if job.get("status") == "pending":
                _write_job(
                    path,
                    {
                        **job,
                        "status": "failed",
                        "error": "任务提交或调度失败；可恢复已保存的任务。",
                    },
                )
                export_tokens.pop((project_id, task_id), None)

        def run() -> None:
            started = monotonic()
            running = {**pending, "status": "running"}
            try:
                _write_job(path, running)
                token.raise_if_cancelled()
                result = operation()
                _write_job(
                    path,
                    {
                        **running,
                        "status": "succeeded",
                        "result": result,
                        "progress": {
                            "phase": "completed",
                            "elapsed_seconds": round(monotonic() - started, 2),
                        },
                    },
                )
            except TranscriptionCancelled:
                _write_job(path, {**running, "status": "cancelled"})
            except (
                MiniCutError,
                TextModelProviderError,
                ValueError,
                TimeoutError,
            ) as error:
                _write_job(
                    path,
                    {**running, "status": "failed", "error": str(error)},
                )
            except Exception:
                _write_job(
                    path,
                    {
                        **running,
                        "status": "failed",
                        "error": "Task failed; completed stages are retained for recovery",
                    },
                )
            finally:
                export_tokens.pop((project_id, task_id), None)

        def settle(_future: Future[None]) -> None:
            export_tokens.pop((project_id, task_id), None)
            task_futures.pop((project_id, task_id), None)

        try:
            response = _task_response(pending)
            runner = _TaskRunner(
                run,
                fail_submission,
                export_workers
                if kind in {"output-export", "output-preview", "render"}
                else compute_workers,
                settle,
                (project_id, task_id),
            )
            if runners is None:
                schedule_runners([runner], background_tasks)
            else:
                runners.append(runner)
            return response
        except Exception:
            fail_submission()
            raise

    def fail_submissions(runners: list[_TaskRunner]) -> None:
        # Attempt every cleanup even if one task file cannot be updated.
        first_error: Exception | None = None
        try:
            for runner in runners:
                try:
                    runner.fail_submission()
                except Exception as error:
                    if first_error is None:
                        first_error = error
        finally:
            runners.clear()
        if first_error is not None:
            raise first_error

    async def observe_runners(runners: list[_TaskRunner]) -> None:
        # Keep graceful shutdown tracking without occupying HTTP worker threads.
        await asyncio.gather(
            *(wait_for_task(runner.future) for runner in runners if runner.future)
        )

    def schedule_runners(
        runners: list[_TaskRunner], background: BackgroundTasks
    ) -> None:
        if not runners:
            return
        try:
            background.add_task(observe_runners, runners)
            futures = runners[0].pool.submit_many([runner.run for runner in runners])
            for runner, future in zip(runners, futures, strict=True):
                runner.future = future
                task_futures[runner.identity] = (runner.pool, future)
                future.add_done_callback(runner.settle)
        except TaskQueueFull as error:
            fail_submissions(runners)
            raise HTTPException(503, str(error)) from error
        except Exception:
            fail_submissions(runners)
            raise

    @api.get("/api/projects/{project_id}/activity")
    def project_activity(project_id: ProjectId) -> dict[str, object]:  # pyright: ignore[reportUnusedFunction]
        from minicut.model_journal import ModelJournal

        inspect(project_id)
        directory = root / project_id
        paths = sorted(
            (directory / ".minicut/jobs").glob("*.json"),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )[:20]
        jobs = [_task_response(_read_job(path)).model_dump() for path in paths]
        receipts: list[dict[str, object]] = []
        if (directory / ".minicut/model-requests.sqlite3").is_file():
            with ModelJournal(directory).connect() as db:
                for identity, state, receipt in db.execute(
                    "SELECT id,status,receipt FROM requests ORDER BY id DESC LIMIT 100"
                ):
                    receipts.append(
                        {**json.loads(receipt), "request_id": identity, "status": state}
                    )
        return {
            "tasks": jobs,
            "model_requests": receipts,
            "heavy_task_concurrency": 1,
            "export_task_concurrency": export_concurrency,
        }

    @api.post(
        "/api/projects",
        response_model=ProjectDetailResponse,
        response_model_exclude_none=True,
        status_code=status.HTTP_201_CREATED,
    )
    def create_project(  # pyright: ignore[reportUnusedFunction]
        body: ProjectCreateBody,
    ) -> ProjectDetailResponse:
        project_id = body.project_id or f"project-{uuid4().hex}"
        try:
            initializer.execute(
                InitProjectRequest(root / project_id, project_id, body.name)
            )
        except MiniCutError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        result = inspect(project_id)
        return ProjectDetailResponse(
            project_id=result.project_id,
            asset_count=len(result.asset_ids),
            asset_ids=list(result.asset_ids),
            name=body.name,
        )

    @api.get(
        "/api/projects",
        response_model=list[ProjectSummaryResponse],
        response_model_exclude_none=True,
    )
    def list_projects(  # pyright: ignore[reportUnusedFunction]
    ) -> list[ProjectSummaryResponse]:
        if not root.is_dir():
            return []
        projects: list[ProjectSummaryResponse] = []
        for child in sorted(root.iterdir(), key=lambda path: path.name):
            if not (child / "manifest.json").is_file():
                continue
            result = inspect(child.name)
            projects.append(
                ProjectSummaryResponse(
                    project_id=result.project_id,
                    asset_count=len(result.asset_ids),
                    name=ProjectRepository(child).read().name,
                )
            )
        return projects

    @api.get(
        "/api/projects/{project_id}",
        response_model=ProjectDetailResponse,
        response_model_exclude_none=True,
    )
    def get_project(  # pyright: ignore[reportUnusedFunction]
        project_id: ProjectId,
    ) -> ProjectDetailResponse:
        result = inspect(project_id)
        return ProjectDetailResponse(
            project_id=result.project_id,
            asset_count=len(result.asset_ids),
            asset_ids=list(result.asset_ids),
            name=ProjectRepository(root / project_id).read().name,
        )

    @api.delete("/api/projects/{project_id}")
    def delete_project(project_id: ProjectId) -> dict[str, bool]:  # pyright: ignore[reportUnusedFunction]
        directory = root / project_id
        if directory.is_symlink() or directory.resolve().parent != root.resolve():
            raise HTTPException(status_code=400, detail="不能删除项目根目录外的路径")
        if not (directory / "manifest.json").is_file():
            raise HTTPException(status_code=404, detail="项目不存在")
        for path in (directory / ".minicut/jobs").glob("*.json"):
            if _read_job(path).get("status") in {"pending", "running"}:
                raise HTTPException(
                    status_code=409, detail="项目仍有任务运行，请取消或等待完成后删除"
                )
        try:
            shutil.rmtree(directory)
        except OSError as error:
            raise HTTPException(
                status_code=500, detail="删除未完成，请检查目录权限后重试"
            ) from error
        return {"deleted": True}

    @api.get("/api/projects/{project_id}/assets")
    def list_assets(project_id: ProjectId) -> list[dict[str, object]]:  # pyright: ignore[reportUnusedFunction]
        inspect(project_id)
        directory = root / project_id
        return [
            {
                "asset_id": asset.asset_id,
                "name": Path(asset.source_path).name,
                "duration_ms": asset.duration_ms,
                "has_transcript": (
                    directory / ".minicut/transcripts" / f"{asset.asset_id}.json"
                ).is_file(),
                "has_plan": (
                    directory / ".minicut/plans" / f"{asset.asset_id}.json"
                ).is_file(),
            }
            for asset in ProjectRepository(directory).read().assets
        ]

    @api.post("/api/projects/{project_id}/assets", status_code=201)
    async def upload_asset(  # pyright: ignore[reportUnusedFunction]
        project_id: ProjectId, filename: str, request: Request
    ) -> dict[str, object]:
        inspect(project_id)
        if (
            not filename
            or len(filename) > 200
            or any(character in filename for character in ("/", "\\", "\x00"))
            or any(ord(character) < 32 for character in filename)
            or (os.name == "nt" and not valid_windows_filename(filename))
        ):
            raise HTTPException(400, "Invalid media filename")
        try:
            classify_media(filename)
        except MiniCutError as error:
            raise HTTPException(400, str(error)) from error
        directory = root / project_id / ".minicut/media" / uuid4().hex
        directory.mkdir(parents=True)
        destination = directory / filename
        retained = False
        try:
            with destination.open("xb") as target:
                async for chunk in request.stream():
                    await run_in_threadpool(target.write, chunk)
            asset = await run_in_threadpool(
                import_media, ProjectRepository(root / project_id), destination
            )
            retained = Path(asset.source_path) == destination
            return {
                "asset_id": asset.asset_id,
                "name": Path(asset.source_path).name,
                "duration_ms": asset.duration_ms,
            }
        except MiniCutError as error:
            raise HTTPException(400, str(error)) from error
        except OSError as error:
            raise HTTPException(500, "Media could not be stored") from error
        finally:
            if not retained:
                destination.unlink(missing_ok=True)
                directory.rmdir()

    task_key_header = Header(
        alias="Idempotency-Key",
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )

    def resolve_output_export(
        project_id: ProjectId,
        body: OutputExportBody,
        idempotency_key: str,
    ) -> OutputExportBody:
        existing_path = _job_path(root / project_id, idempotency_key)
        if body.cover_version is None and existing_path.is_file():
            existing_request = _read_job(existing_path).get("request")
            if isinstance(existing_request, dict):
                body = body.model_copy(
                    update={
                        "cover_version": cast(dict[str, object], existing_request).get(
                            "cover_version", 0
                        )
                    }
                )
        store = CoverStore(root / project_id, body.collection_id, body.output_id)
        saved_cover = (
            store.read(body.cover_version) if body.cover_version != 0 else None
        )
        if body.cover_version and saved_cover is None:
            raise HTTPException(400, "保存的封面版本不存在")
        body = body.model_copy(
            update={
                "cover_version": saved_cover[0] if saved_cover else 0,
                "cover_snapshot": saved_cover[1] if saved_cover else None,
            }
        )
        if existing_path.is_file():
            existing_task(existing_path, "output-export", body.model_dump(mode="json"))
        return body

    def enqueue_output_export(
        project_id: ProjectId,
        body: OutputExportBody,
        background_tasks: BackgroundTasks,
        idempotency_key: str,
        runners: list[_TaskRunner] | None = None,
    ) -> TaskResponse:

        def operation() -> dict[str, object]:
            token = export_tokens.setdefault(
                (project_id, idempotency_key), CancellationToken()
            )
            try:
                return export_output(
                    root / project_id,
                    body.collection_id,
                    body.output_id,
                    idempotency_key,
                    body.revision,
                    body.subtitle_mode,
                    body.audio_fade_ms,
                    body.denoiser_id,
                    token,
                    RenderProfile(
                        body.aspect_ratio,
                        body.resolution,
                        body.fit,
                        body.crop_left,
                        body.crop_right,
                        body.crop_top,
                        body.crop_bottom,
                    ),
                    False,
                    body.cover_snapshot,
                    body.cover_version,
                    body.subtitle_settings,
                )
            finally:
                export_tokens.pop((project_id, idempotency_key), None)

        response = submit_task(
            project_id,
            idempotency_key,
            "output-export",
            body.model_dump(mode="json"),
            background_tasks,
            operation,
            runners=runners,
        )
        if response.status not in ("pending", "running"):
            export_tokens.pop((project_id, idempotency_key), None)
        return response

    @api.post(
        "/api/projects/{project_id}/tasks/output-export",
        response_model=TaskResponse,
        status_code=202,
    )
    def submit_output_export(  # pyright: ignore[reportUnusedFunction]
        project_id: ProjectId,
        body: OutputExportBody,
        background_tasks: BackgroundTasks,
        idempotency_key: Annotated[str, task_key_header],
    ) -> TaskResponse:
        return enqueue_output_export(
            project_id,
            resolve_output_export(project_id, body, idempotency_key),
            background_tasks,
            idempotency_key,
        )

    @api.post(
        "/api/projects/{project_id}/tasks/output-export-batch",
        response_model=list[TaskResponse],
        status_code=202,
    )
    def submit_output_batch(  # pyright: ignore[reportUnusedFunction]
        project_id: ProjectId,
        body: OutputExportBatchBody,
        background_tasks: BackgroundTasks,
        idempotency_key: Annotated[str, task_key_header],
    ) -> list[TaskResponse]:
        inspect(project_id)
        outputs = [
            resolve_output_export(
                project_id,
                output,
                f"{idempotency_key}-{output.output_id}",
            )
            for output in body.outputs
        ]
        runners: list[_TaskRunner] = []
        try:
            responses = [
                enqueue_output_export(
                    project_id,
                    output,
                    background_tasks,
                    f"{idempotency_key}-{output.output_id}",
                    runners,
                )
                for output in outputs
            ]
            schedule_runners(runners, background_tasks)
            return responses
        except Exception:
            fail_submissions(runners)
            raise

    @api.post(
        "/api/projects/{project_id}/tasks/output-preview",
        response_model=TaskResponse,
        status_code=202,
    )
    def submit_output_preview(  # pyright: ignore[reportUnusedFunction]
        project_id: ProjectId,
        body: OutputPreviewBody,
        background_tasks: BackgroundTasks,
        idempotency_key: Annotated[str, task_key_header],
    ) -> TaskResponse:
        token = export_tokens.setdefault(
            (project_id, idempotency_key), CancellationToken()
        )

        def operation() -> dict[str, object]:
            try:
                return preview_output(
                    root / project_id,
                    body.collection_id,
                    body.output_id,
                    body.revision,
                    token,
                    PreviewOptions.model_validate(
                        body.model_dump(include=set(PreviewOptions.model_fields))
                    ),
                )
            finally:
                export_tokens.pop((project_id, idempotency_key), None)

        response = submit_task(
            project_id,
            idempotency_key,
            "output-preview",
            body.model_dump(mode="json"),
            background_tasks,
            operation,
        )
        if response.status not in ("pending", "running"):
            export_tokens.pop((project_id, idempotency_key), None)
        return response

    @api.get(
        "/api/projects/{project_id}/highlights/{collection_id}/outputs/{output_id}/preview-task",
        response_model=TaskResponse | None,
    )
    def latest_output_preview(  # pyright: ignore[reportUnusedFunction]
        project_id: ProjectId,
        collection_id: SafeFileName,
        output_id: SafeFileName,
        settings: Annotated[OutputPreviewQuery, Query()],
    ) -> TaskResponse | None:
        inspect(project_id)
        paths = sorted(
            (root / project_id / ".minicut/jobs").glob("*.json"),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
        for path in paths:
            job = _read_job(path)
            data = job.get("request")
            if isinstance(data, dict):
                data = cast(dict[str, object], data)
                if (
                    job.get("kind") == "output-preview"
                    and data.get("collection_id") == collection_id
                    and data.get("output_id") == output_id
                    and data.get("revision") == settings.revision
                    and PreviewOptions.model_validate(
                        {
                            key: data[key]
                            for key in PreviewOptions.model_fields
                            if key in data
                        }
                    ).model_dump()
                    == settings.model_dump(exclude={"revision"})
                ):
                    result = job.get("result")
                    if job.get("status") == "succeeded" and (
                        not isinstance(result, dict)
                        or cast(dict[str, object], result).get("render_engine_version")
                        != RENDER_ENGINE_VERSION
                    ):
                        continue
                    return _task_response(job)
        return None

    @api.post(
        "/api/projects/{project_id}/tasks/{task_id}/cancel", response_model=TaskResponse
    )
    def cancel_export(  # pyright: ignore[reportUnusedFunction]
        project_id: ProjectId,
        task_id: SafeFileName,
    ) -> TaskResponse:
        inspect(project_id)
        job = _read_job(_job_path(root / project_id, task_id))
        if job.get("status") not in ("pending", "running"):
            return _task_response(job)
        token = export_tokens.get((project_id, task_id))
        if token is None:
            raise HTTPException(
                409,
                "This task cannot be cancelled by this server; it may predate a restart",
            )
        token.cancel()
        queued = task_futures.get((project_id, task_id))
        if queued is not None:
            pool, future = queued
            if pool.cancel(
                future,
                on_cancel=lambda: _write_job(
                    _job_path(root / project_id, task_id),
                    {**job, "status": "cancelled"},
                ),
            ):
                job = _read_job(_job_path(root / project_id, task_id))
        return _task_response(job)

    @api.get(
        "/api/projects/{project_id}/highlights/{collection_id}/outputs/{output_id}/export-task",
        response_model=TaskResponse | None,
    )
    def latest_output_export(  # pyright: ignore[reportUnusedFunction]
        project_id: ProjectId,
        collection_id: SafeFileName,
        output_id: SafeFileName,
    ) -> TaskResponse | None:
        inspect(project_id)
        paths = sorted(
            (root / project_id / ".minicut/jobs").glob("*.json"),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
        for path in paths:
            job = _read_job(path)
            data = job.get("request")
            data = cast(dict[str, object], data) if isinstance(data, dict) else None
            if (
                job.get("kind") == "output-export"
                and isinstance(data, dict)
                and data.get("collection_id") == collection_id
                and data.get("output_id") == output_id
            ):
                return _task_response(job)
        return None

    @api.post(
        "/api/projects/{project_id}/tasks/transcribe",
        response_model=TaskResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def submit_transcription(  # pyright: ignore[reportUnusedFunction]
        project_id: ProjectId,
        body: TranscribeTaskBody,
        background_tasks: BackgroundTasks,
        idempotency_key: Annotated[str, task_key_header],
    ) -> TaskResponse:
        request_data = body.model_dump(mode="json", exclude_none=True)
        source = body.source_path
        if body.asset_id is not None:
            inspect(project_id)
            asset = next(
                (
                    item
                    for item in ProjectRepository(root / project_id).read().assets
                    if item.asset_id == body.asset_id
                ),
                None,
            )
            if asset is None:
                raise HTTPException(404, "Asset does not exist")
            source = asset.source_path
        assert source is not None

        def operation() -> dict[str, object]:
            result = transcriber.execute(
                TranscribeRequest(
                    root / project_id,
                    Path(source),
                    body.provider,
                    body.model,
                    body.language,
                    export_tokens.setdefault(
                        (project_id, idempotency_key), CancellationToken()
                    ),
                    lambda done, total: progress(
                        project_id, idempotency_key, done, total
                    ),
                )
            )
            return {
                "transcript_id": result.transcript_id,
                "asset_id": result.asset_id,
                "word_count": result.word_count,
                "reused": result.reused,
            }

        return submit_task(
            project_id,
            idempotency_key,
            "transcribe",
            request_data,
            background_tasks,
            operation,
        )

    @api.get(
        "/api/projects/{project_id}/assets/{asset_id}/transcription-task",
        response_model=TaskResponse | None,
    )
    def latest_transcription(  # pyright: ignore[reportUnusedFunction]
        project_id: ProjectId, asset_id: SafeFileName
    ) -> TaskResponse | None:
        inspect(project_id)
        asset = next(
            (
                item
                for item in ProjectRepository(root / project_id).read().assets
                if item.asset_id == asset_id
            ),
            None,
        )
        if asset is None:
            raise HTTPException(404, "Asset does not exist")
        jobs = sorted(
            (root / project_id / ".minicut/jobs").glob("*.json"),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
        for path in jobs:
            job = _read_job(path)
            request = cast(dict[str, object], job.get("request", {}))
            if job.get("kind") == "transcribe" and (
                request.get("asset_id") == asset_id
                or request.get("source_path") == asset.source_path
            ):
                return _task_response(job)
        return None

    def generation_asset(project_id: str, asset_id: str) -> None:
        inspect(project_id)
        if not any(
            asset.asset_id == asset_id
            for asset in ProjectRepository(root / project_id).read().assets
        ):
            raise HTTPException(404, "Asset does not exist")

    def generation_history(
        project_id: str, asset_id: str | None = None
    ) -> list[dict[str, object]]:
        directory = root / project_id
        assets = {
            asset.asset_id: Path(asset.source_path).name
            for asset in ProjectRepository(directory).read().assets
        }
        fields = set(HighlightTaskBody.model_fields) - {
            "cleanup_version",
            "boundary_version",
            "asset_id",
            "custom_preset_id",
            "custom_preset_name",
            "editing_prompt",
        }

        def missing_fields(brief: dict[str, object]) -> list[str]:
            expected = fields
            if brief.get("editing_prompt") is not None:
                expected = (fields - {"preset_prompt", "instructions"}) | {
                    "editing_prompt"
                }
            return sorted(
                key
                for key in expected
                if key not in brief or (key == "preset_prompt" and brief[key] is None)
            )

        entries: list[tuple[int, dict[str, object]]] = []
        collections: set[str] = set()

        def order(path: Path, record: dict[str, object]) -> int:
            created = record.get("created_at")
            if isinstance(created, str):
                return int(datetime.fromisoformat(created).timestamp() * 1_000_000_000)
            return path.stat().st_mtime_ns

        for path in (directory / ".minicut/jobs").glob("*.json"):
            job = _read_job(path)
            if job.get("kind") != "highlights":
                continue
            request = cast(dict[str, object], job.get("request", {}))
            if asset_id is not None and request.get("asset_id") != asset_id:
                continue
            result = cast(dict[str, object], job.get("result") or {})
            brief = cast(
                dict[str, object],
                job.get("generation_config")
                or result.get("brief")
                or {
                    key: value
                    for key, value in request.items()
                    if key in fields or key == "editing_prompt" and value is not None
                },
            )
            collection = result.get("collection_id") or f"highlights-{job['task_id']}"
            collections.add(str(collection))
            entries.append(
                (
                    order(path, job),
                    {
                        "history_id": job["task_id"],
                        "asset_id": request.get("asset_id"),
                        "asset_name": assets.get(str(request.get("asset_id"))),
                        "created_at": job.get("created_at"),
                        "status": job["status"],
                        "error": job.get("error"),
                        "collection_id": collection,
                        "brief": brief,
                        "custom_preset_id": request.get("custom_preset_id"),
                        "custom_preset_name": request.get("custom_preset_name"),
                        "missing_fields": missing_fields(brief),
                    },
                )
            )
        # Older results may survive without their original job file.
        for path in (directory / ".minicut/highlight-results").glob("*.json"):
            result = cast(
                dict[str, object], json.loads(path.read_text(encoding="utf-8"))
            )
            if path.stem in collections or (
                asset_id is not None and result.get("asset_id") != asset_id
            ):
                continue
            brief = cast(dict[str, object], result.get("brief") or {})
            entries.append(
                (
                    order(path, result),
                    {
                        "history_id": path.stem,
                        "asset_id": result.get("asset_id"),
                        "asset_name": assets.get(str(result.get("asset_id"))),
                        "created_at": result.get("created_at"),
                        "status": "succeeded",
                        "error": None,
                        "collection_id": path.stem,
                        "brief": brief,
                        "custom_preset_id": result.get("custom_preset_id"),
                        "custom_preset_name": result.get("custom_preset_name"),
                        "missing_fields": missing_fields(brief),
                    },
                )
            )
        return [
            entry
            for _, entry in sorted(entries, key=lambda pair: pair[0], reverse=True)
        ]

    @api.get("/api/projects/{project_id}/generation-history")
    def list_generation_history(  # pyright: ignore[reportUnusedFunction]
        project_id: ProjectId, asset_id: SafeFileName | None = None
    ) -> list[dict[str, object]]:
        inspect(project_id)
        if asset_id is not None:
            generation_asset(project_id, asset_id)
        return generation_history(project_id, asset_id)

    @api.get("/api/projects/{project_id}/assets/{asset_id}/generation-draft")
    def get_generation_draft(  # pyright: ignore[reportUnusedFunction]
        project_id: ProjectId, asset_id: SafeFileName
    ) -> dict[str, object]:
        generation_asset(project_id, asset_id)
        settings = GenerationSettings(root / project_id)
        own = settings.read(asset_id)
        if own is not None:
            return {**own, "source": "asset"}
        history = generation_history(project_id, asset_id)
        if history:
            return {"source": "history", "history": history[0], "draft": None}
        recent = settings.read()
        if recent is not None:
            return {**recent, "source": "project"}
        project_history = generation_history(project_id)
        if project_history:
            return {
                "source": "project_history",
                "history": project_history[0],
                "draft": None,
            }
        return {"source": "default", "draft": None}

    @api.put("/api/projects/{project_id}/assets/{asset_id}/generation-draft")
    def save_generation_draft(  # pyright: ignore[reportUnusedFunction]
        project_id: ProjectId, asset_id: SafeFileName, body: GenerationDraft
    ) -> dict[str, object]:
        generation_asset(project_id, asset_id)
        return {
            **GenerationSettings(root / project_id).save(asset_id, body),
            "source": "asset",
        }

    @api.post(
        "/api/projects/{project_id}/tasks/highlights",
        response_model=TaskResponse,
        status_code=202,
    )
    def submit_highlights(  # pyright: ignore[reportUnusedFunction]
        project_id: ProjectId,
        body: HighlightTaskBody,
        background_tasks: BackgroundTasks,
        idempotency_key: Annotated[str, task_key_header],
    ) -> TaskResponse:
        inspect(project_id)
        existing_path = _job_path(root / project_id, idempotency_key)
        if existing_path.is_file():
            existing = _read_job(existing_path)
            existing_request = existing.get("request")
            if existing.get("kind") == "highlights" and isinstance(
                existing_request, dict
            ):
                saved_request = cast(dict[str, object], existing_request)
                # An omitted version must retain the saved task's pipeline,
                # including legacy tasks that predate version fields.
                body = body.model_copy(
                    update={
                        field: saved_request.get(field)
                        for field in ("cleanup_version", "boundary_version")
                        if field not in body.model_fields_set
                    }
                )
        manifest = ProjectRepository(root / project_id).read()
        if not any(asset.asset_id == body.asset_id for asset in manifest.assets):
            raise HTTPException(404, "Asset does not exist")
        if not (
            root / project_id / ".minicut/transcripts" / f"{body.asset_id}.json"
        ).is_file():
            raise HTTPException(400, "Transcription is required")

        # Resolve defaults once so the snapshot and the actual generation agree.
        resolved = HighlightTaskBody.model_validate(
            {
                "asset_id": body.asset_id,
                "cleanup_version": None,
                "boundary_version": None,
                **body.brief().to_dict(),
            }
        ).brief()

        def operation() -> dict[str, object]:
            collection = f"highlights-{idempotency_key}"
            if highlights is generate_highlights:
                return generate_highlights(
                    root / project_id,
                    body.asset_id,
                    collection,
                    resolved,
                    cancellation=export_tokens.setdefault(
                        (project_id, idempotency_key), CancellationToken()
                    ),
                )
            return highlights(root / project_id, body.asset_id, collection, resolved)

        request_data = body.model_dump(mode="json")
        request_data["cleanup_version"] = resolved.cleanup_version
        request_data["boundary_version"] = resolved.boundary_version
        # Retain old idempotency requests when no custom template was used.
        for field in (
            "custom_preset_id",
            "custom_preset_name",
            "editing_prompt",
            "cleanup_version",
            "boundary_version",
        ):
            if request_data[field] is None:
                request_data.pop(field)
        return submit_task(
            project_id,
            idempotency_key,
            "highlights",
            request_data,
            background_tasks,
            operation,
            generation_config=resolved.to_dict(),
        )

    @api.get(
        "/api/projects/{project_id}/assets/{asset_id}/highlight-task",
        response_model=TaskResponse | None,
    )
    def latest_highlights(  # pyright: ignore[reportUnusedFunction]
        project_id: ProjectId,
        asset_id: SafeFileName,
    ) -> TaskResponse | None:
        inspect(project_id)
        jobs = sorted(
            (root / project_id / ".minicut/jobs").glob("*.json"),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
        for path in jobs:
            job = _read_job(path)
            request = cast(dict[str, object], job.get("request", {}))
            if job.get("kind") == "highlights" and request.get("asset_id") == asset_id:
                return _task_response(job)
        return None

    @api.get("/api/projects/{project_id}/highlights/{collection_id}")
    def get_highlights(  # pyright: ignore[reportUnusedFunction]
        project_id: ProjectId,
        collection_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")],
    ) -> dict[str, object]:
        inspect(project_id)
        try:
            return read_highlights(root / project_id, collection_id)
        except MiniCutError as error:
            raise HTTPException(404, str(error)) from error

    @api.put("/api/projects/{project_id}/highlights/{collection_id}/selection")
    def save_highlight_selection(  # pyright: ignore[reportUnusedFunction]
        project_id: ProjectId,
        collection_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")],
        body: HighlightSelectionBody,
    ) -> dict[str, object]:
        inspect(project_id)
        try:
            result = read_highlights(root / project_id, collection_id)
            allowed = {
                output["output_id"]
                for output in cast(list[dict[str, object]], result["outputs"])
            }
            if (
                len(set(body.output_ids)) != len(body.output_ids)
                or not set(body.output_ids) <= allowed
            ):
                raise HTTPException(
                    400, "Selection contains unknown or repeated outputs"
                )
            result["selected_output_ids"] = body.output_ids
            OutputCollectionRepository(
                root / project_id, collection_id
            ).write_highlight_result(result)
            return result
        except MiniCutError as error:
            raise HTTPException(400, str(error)) from error

    @api.post(
        "/api/projects/{project_id}/highlights/{collection_id}/outputs/{output_id}/split-sentences"
    )
    def split_sentences(  # pyright: ignore[reportUnusedFunction]
        project_id: ProjectId,
        collection_id: ProjectId,
        output_id: ProjectId,
        base_revision: int,
    ) -> dict[str, object]:
        from minicut.highlight_service import split_saved_output

        try:
            return split_saved_output(
                root / project_id, collection_id, output_id, base_revision
            )
        except UserInputError as error:
            raise HTTPException(
                status_code=409 if "版本冲突" in str(error) else 400,
                detail=str(error),
            ) from error

    @api.post(
        "/api/projects/{project_id}/highlights/{collection_id}/outputs/{output_id}/items/{instance_id}/split"
    )
    def manual_split(  # pyright: ignore[reportUnusedFunction]
        project_id: ProjectId,
        collection_id: ProjectId,
        output_id: ProjectId,
        instance_id: str,
        body: ManualSplitBody,
    ) -> dict[str, object]:
        from minicut.highlight_service import manual_split_output

        try:
            return manual_split_output(
                root / project_id,
                collection_id,
                output_id,
                instance_id,
                body.base_revision,
                body.lines,
                body.apply,
            )
        except (UserInputError, ValueError) as error:
            raise HTTPException(
                status_code=409 if "版本冲突" in str(error) else 400,
                detail=str(error),
            ) from error

    @api.put(
        "/api/projects/{project_id}/highlights/{collection_id}/outputs/{output_id}/ranges"
    )
    def put_output_ranges(  # pyright: ignore[reportUnusedFunction]
        project_id: ProjectId,
        collection_id: str,
        output_id: str,
        body: OutputRangesBody,
    ) -> dict[str, object]:  # pyright: ignore[reportUnusedFunction]
        inspect(project_id)
        try:
            return save_output_ranges(
                root / project_id,
                collection_id,
                output_id,
                body.base_revision,
                [row.model_dump() for row in body.ranges],
            )
        except RevisionConflict as error:
            raise HTTPException(409, str(error)) from error
        except (MiniCutError, ValueError) as error:
            raise HTTPException(400, str(error)) from error

    @api.put(
        "/api/projects/{project_id}/highlights/{collection_id}/outputs/{output_id}/title"
    )
    def put_output_title(  # pyright: ignore[reportUnusedFunction]
        project_id: ProjectId,
        collection_id: SafeFileName,
        output_id: SafeFileName,
        body: OutputTitleBody,
    ) -> dict[str, object]:
        from minicut.highlight_service import rename_output

        inspect(project_id)
        try:
            return rename_output(
                root / project_id,
                collection_id,
                output_id,
                body.base_revision,
                body.title,
            )
        except RevisionConflict as error:
            raise HTTPException(409, str(error)) from error
        except (MiniCutError, ValueError) as error:
            raise HTTPException(400, str(error)) from error

    @api.patch(
        "/api/projects/{project_id}/highlights/{collection_id}/outputs/{output_id}/items/{instance_id}"
    )
    def patch_output_item(  # pyright: ignore[reportUnusedFunction]
        project_id: ProjectId,
        collection_id: str,
        output_id: str,
        instance_id: str,
        body: OutputItemEditBody,
    ) -> dict[str, object]:
        inspect(project_id)
        try:
            return edit_output_item(
                root / project_id,
                collection_id,
                output_id,
                instance_id,
                deleted=body.deleted,
                display_text=body.display_text,
                translation_text=body.translation_text,
                subtitle_mode=body.subtitle_mode,
                source_start_ms=body.source_start_ms,
                source_end_ms=body.source_end_ms,
            )
        except (MiniCutError, ValueError) as error:
            raise HTTPException(400, str(error)) from error

    @api.put(
        "/api/projects/{project_id}/highlights/{collection_id}/outputs/{output_id}/subtitle-settings"
    )
    def put_output_subtitle_settings(  # pyright: ignore[reportUnusedFunction]
        project_id: ProjectId,
        collection_id: SafeFileName,
        output_id: SafeFileName,
        body: OutputSubtitleSettingsBody,
    ) -> dict[str, object]:
        inspect(project_id)
        try:
            return save_output_subtitle_settings(
                root / project_id,
                collection_id,
                output_id,
                **body.model_dump(),
                replace_subtitle_style="subtitle_style" in body.model_fields_set,
            )
        except RevisionConflict as error:
            raise HTTPException(409, str(error)) from error
        except (MiniCutError, ValueError) as error:
            raise HTTPException(400, str(error)) from error

    @api.post(
        "/api/projects/{project_id}/tasks/output-translation",
        response_model=TaskResponse,
        status_code=202,
    )
    def submit_output_translation(  # pyright: ignore[reportUnusedFunction]
        project_id: ProjectId,
        body: OutputTranslationBody,
        background_tasks: BackgroundTasks,
        idempotency_key: Annotated[str, task_key_header],
    ) -> TaskResponse:
        inspect(project_id)

        def operation() -> dict[str, object]:
            return translate_output_subtitles(
                root / project_id,
                body.collection_id,
                body.output_id,
                body.base_revision,
                body.language,
                export_tokens.setdefault(
                    (project_id, idempotency_key), CancellationToken()
                ),
            )

        return submit_task(
            project_id,
            idempotency_key,
            "output-translation",
            body.model_dump(),
            background_tasks,
            operation,
        )

    @api.put(
        "/api/projects/{project_id}/highlights/{collection_id}/outputs/{output_id}/order"
    )
    def put_output_order(  # pyright: ignore[reportUnusedFunction]
        project_id: ProjectId,
        collection_id: str,
        output_id: str,
        body: OutputOrderBody,
    ) -> dict[str, object]:
        inspect(project_id)
        try:
            return reorder_output(
                root / project_id,
                collection_id,
                output_id,
                body.order,
                body.roles,
                body.hook_transition_ms,
                body.hook_transition_kind,
            )
        except (MiniCutError, ValueError) as error:
            raise HTTPException(400, str(error)) from error

    @api.get(
        "/api/projects/{project_id}/highlights/{collection_id}/outputs/{output_id}/versions"
    )
    def get_output_versions(  # pyright: ignore[reportUnusedFunction]
        project_id: ProjectId,
        collection_id: str,
        output_id: str,
    ) -> list[dict[str, object]]:
        inspect(project_id)
        try:
            return output_versions(root / project_id, collection_id, output_id)
        except (MiniCutError, ValueError) as error:
            raise HTTPException(400, str(error)) from error

    @api.post(
        "/api/projects/{project_id}/tasks/plan",
        response_model=TaskResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def submit_plan(  # pyright: ignore[reportUnusedFunction]
        project_id: ProjectId,
        body: PlanTaskBody,
        background_tasks: BackgroundTasks,
        idempotency_key: Annotated[str, task_key_header],
    ) -> TaskResponse:
        request_data = body.model_dump(mode="json")

        def operation() -> dict[str, object]:
            result = planner.execute(
                PlanRequest(
                    root / project_id,
                    body.asset_id,
                    body.target_duration_ms,
                    body.intensity,
                    body.style,
                    body.planner,
                )
            )
            return {
                "asset_id": result.asset_id,
                "kept_segments": result.kept_segments,
                "deleted_segments": result.deleted_segments,
                "artifact_path": str(result.artifact_path),
                "summary_path": (
                    None if result.summary_path is None else str(result.summary_path)
                ),
                "reused": result.reused,
            }

        return submit_task(
            project_id,
            idempotency_key,
            "plan",
            request_data,
            background_tasks,
            operation,
        )

    @api.post(
        "/api/projects/{project_id}/tasks/render",
        response_model=TaskResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def submit_render(  # pyright: ignore[reportUnusedFunction]
        project_id: ProjectId,
        body: RenderTaskBody,
        background_tasks: BackgroundTasks,
        idempotency_key: Annotated[str, task_key_header],
    ) -> TaskResponse:
        request_data = body.model_dump(mode="json")

        def operation() -> dict[str, object]:
            output_path = root / project_id / "exports" / body.output_name
            output_path.parent.mkdir(parents=True, exist_ok=True)
            result = renderer.execute(
                RenderRequest(
                    root / project_id,
                    body.asset_id,
                    output_path,
                    body.timeout_seconds,
                )
            )
            return {
                "output_path": str(result.output_path),
                "subtitle_path": str(result.subtitle_path),
                "duration_ms": result.duration_ms,
                "reused": result.reused,
            }

        return submit_task(
            project_id,
            idempotency_key,
            "render",
            request_data,
            background_tasks,
            operation,
        )

    @api.post(
        "/api/projects/{project_id}/tasks/{task_id}/resume",
        response_model=TaskResponse,
        status_code=202,
    )
    def resume_task(  # pyright: ignore[reportUnusedFunction]
        project_id: ProjectId, task_id: SafeFileName, background_tasks: BackgroundTasks
    ) -> TaskResponse:  # pyright: ignore[reportUnusedFunction]
        inspect(project_id)
        with resume_lock:
            path = _job_path(root / project_id, task_id)
            job = _read_job(path)
            existing = job.get("resumed_task_id")
            if isinstance(existing, str):
                return _task_response(_read_job(_job_path(root / project_id, existing)))
            if job.get("status") not in ("failed", "cancelled"):
                raise HTTPException(
                    409, "Only interrupted, failed or cancelled tasks can be resumed"
                )
            response = dispatch_resume(project_id, job, background_tasks)
            _write_job(path, {**job, "resumed_task_id": response.task_id})
            return response

    def dispatch_resume(
        project_id: str, job: dict[str, object], background_tasks: BackgroundTasks
    ) -> TaskResponse:
        request = job.get("request")
        identity = f"resume-{uuid4().hex}"
        if job.get("kind") == "transcribe":
            return submit_transcription(
                project_id,
                TranscribeTaskBody.model_validate(request),
                background_tasks,
                identity,
            )
        if job.get("kind") == "highlights":
            if isinstance(request, dict) and isinstance(
                job.get("generation_config"), dict
            ):
                request = {
                    **cast(dict[str, object], request),
                    **cast(dict[str, object], job["generation_config"]),
                }
            request = {
                "cleanup_version": None,
                "boundary_version": None,
                **cast(dict[str, object], request),
            }
            body = HighlightTaskBody.model_validate(request)
            try:
                OutputCollectionRepository(
                    root / project_id, f"highlights-{identity}"
                ).inherit_source_transcript(
                    body.asset_id, f"highlights-{job['task_id']}"
                )
            except (MiniCutError, ValueError) as error:
                raise HTTPException(400, str(error)) from error
            return submit_highlights(
                project_id,
                body,
                background_tasks,
                identity,
            )
        if job.get("kind") == "output-export":
            return submit_output_export(
                project_id,
                OutputExportBody.model_validate(
                    {"cover_version": 0, **cast(dict[str, object], request)}
                ),
                background_tasks,
                identity,
            )
        if job.get("kind") == "output-preview":
            return submit_output_preview(
                project_id,
                OutputPreviewBody.model_validate(request),
                background_tasks,
                identity,
            )
        raise HTTPException(400, "This task type does not support recovery")

    @api.get(
        "/api/projects/{project_id}/tasks/{task_id}",
        response_model=TaskResponse,
    )
    def get_task(  # pyright: ignore[reportUnusedFunction]
        project_id: ProjectId,
        task_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")],
    ) -> TaskResponse:
        inspect(project_id)
        return _task_response(_read_job(_job_path(root / project_id, task_id)))

    @api.get(
        "/api/projects/{project_id}/plans/{asset_id}",
        response_model=PlanDetailResponse,
    )
    def get_plan(  # pyright: ignore[reportUnusedFunction]
        project_id: ProjectId,
        asset_id: str,
    ) -> PlanDetailResponse:
        return _plan_response(read_plan_result(project_id, asset_id))

    @api.get(
        "/api/projects/{project_id}/plans/{asset_id}/versions",
        response_model=PlanVersionsResponse,
    )
    def list_plan_versions(  # pyright: ignore[reportUnusedFunction]
        project_id: ProjectId,
        asset_id: str,
    ) -> PlanVersionsResponse:
        result = read_plan_result(project_id, asset_id)
        return PlanVersionsResponse(
            asset_id=asset_id,
            current_revision=result.revision,
            revisions=list(result.available_revisions),
        )

    @api.get(
        "/api/projects/{project_id}/plans/{asset_id}/versions/{revision}",
        response_model=PlanDetailResponse,
    )
    def get_plan_version(  # pyright: ignore[reportUnusedFunction]
        project_id: ProjectId,
        asset_id: str,
        revision: int,
    ) -> PlanDetailResponse:
        return _plan_response(read_plan_result(project_id, asset_id, revision))

    @api.patch(
        "/api/projects/{project_id}/plans/{asset_id}",
        response_model=PlanDetailResponse,
    )
    def modify_current_plan(  # pyright: ignore[reportUnusedFunction]
        project_id: ProjectId,
        asset_id: str,
        body: ModifyPlanBody,
    ) -> PlanDetailResponse:
        output_path = (
            None
            if body.output_name is None
            else root / project_id / "exports" / body.output_name
        )
        if output_path is not None:
            output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            plan_modifier.execute(
                ModifyPlanRequest(
                    root / project_id,
                    asset_id,
                    tuple(body.restore_segment_ids),
                    tuple(body.delete_segment_ids),
                    output_path,
                    body.timeout_seconds,
                )
            )
        except MiniCutError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return _plan_response(read_plan_result(project_id, asset_id))

    @api.get(
        "/api/projects/{project_id}/plans/{asset_id}/preview",
        response_model=PreviewTimelineResponse,
    )
    def get_preview_timeline(  # pyright: ignore[reportUnusedFunction]
        project_id: ProjectId,
        asset_id: str,
    ) -> PreviewTimelineResponse:
        try:
            result = preview_compiler.execute(
                PreviewTimelineRequest(root / project_id, asset_id)
            )
        except (MiniCutError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return PreviewTimelineResponse(
            asset_id=result.asset_id,
            plan_revision=result.plan_revision,
            estimated_duration_ms=result.timeline.estimated_duration_ms,
            clips=[
                PreviewClipResponse(
                    clip_id=clip.clip_id,
                    segment_ids=list(clip.segment_ids),
                    source_start_ms=clip.source_range.start_ms,
                    source_end_ms=clip.source_range.end_ms,
                    output_start_ms=clip.output_range.start_ms,
                    output_end_ms=clip.output_range.end_ms,
                )
                for clip in result.timeline.clips
            ],
            jump_cut_risks=[
                JumpCutRiskResponse(
                    left_clip_id=risk.left_clip_id,
                    right_clip_id=risk.right_clip_id,
                    removed_gap_ms=risk.removed_gap_ms,
                    output_at_ms=risk.output_at_ms,
                    explanation=risk.explanation,
                )
                for risk in result.jump_cut_risks
            ],
        )

    range_header = Header(alias="Range")

    @api.get("/api/projects/{project_id}/media/source/{asset_id}")
    def get_source_media(  # pyright: ignore[reportUnusedFunction]
        project_id: ProjectId,
        asset_id: str,
        requested_range: Annotated[str | None, range_header] = None,
    ) -> StreamingResponse:
        project_directory = root / project_id
        inspect(project_id)
        manifest = ProjectRepository(project_directory).read()
        asset = next(
            (item for item in manifest.assets if item.asset_id == asset_id), None
        )
        if asset is None:
            raise HTTPException(status_code=404, detail="Media does not exist")
        source_path = Path(asset.source_path).resolve()
        if not source_path.is_file():
            raise HTTPException(status_code=404, detail="Media does not exist")
        return _stream_file(source_path, requested_range)

    @api.get("/api/projects/{project_id}/media/exports/{resource_path:path}")
    def get_exported_media(  # pyright: ignore[reportUnusedFunction]
        project_id: ProjectId,
        resource_path: str,
        requested_range: Annotated[str | None, range_header] = None,
    ) -> StreamingResponse:
        project_directory = root / project_id
        inspect(project_id)
        return _stream_file(
            _resolve_project_resource(project_directory, resource_path),
            requested_range,
        )

    @api.get("/api/subtitle-fonts")
    def get_subtitle_fonts() -> list[dict[str, str]]:  # pyright: ignore[reportUnusedFunction]
        return [
            {"id": key, "name": name}
            for key, (name, _) in available_subtitle_fonts().items()
        ]

    api.include_router(cover_router(root))
    api.include_router(export_settings_router(root))

    def workflow_child(
        project_id: str,
        kind: str,
        data: JsonObject,
        key: str,
        started: Callable[[list[str]], None],
    ) -> JsonObject:
        """Run existing task adapters without holding the workflow's compute slot."""
        background = BackgroundTasks()

        def existing_or_submit(
            identity: str, submit: Callable[[], TaskResponse]
        ) -> TaskResponse:
            job_path = _job_path(root / project_id, identity)
            if not job_path.exists():
                return submit()
            job = _read_job(job_path)
            # Follow the existing recovery chain, including repeated failures.
            while isinstance(job.get("resumed_task_id"), str):
                job = _read_job(
                    _job_path(root / project_id, cast(str, job["resumed_task_id"]))
                )
            if job.get("status") in {"failed", "cancelled"}:
                return resume_task(project_id, cast(str, job["task_id"]), background)
            if job.get("status") in {"pending", "running"}:
                raise HTTPException(409, "上一阶段仍在执行，请稍后继续")
            return _task_response(job)

        if kind == "transcribe":
            responses = [
                existing_or_submit(
                    key,
                    lambda: submit_transcription(
                        project_id,
                        TranscribeTaskBody.model_validate(data),
                        background,
                        key,
                    ),
                )
            ]
        elif kind == "highlights":
            responses = [
                existing_or_submit(
                    key,
                    lambda: submit_highlights(
                        project_id,
                        HighlightTaskBody.model_validate(data),
                        background,
                        key,
                    ),
                )
            ]
        else:
            # Use the same bounded FFmpeg worker pool as ordinary batch exports.
            runners: list[_TaskRunner] = []
            responses: list[TaskResponse] = []
            try:
                for output in cast(list[JsonObject], data["outputs"]):
                    body = OutputExportBody.model_validate(output)
                    identity = f"{key}-{body.output_id}"
                    response = existing_or_submit(
                        identity,
                        lambda body=body, identity=identity: enqueue_output_export(
                            project_id,
                            resolve_output_export(project_id, body, identity),
                            background,
                            identity,
                            runners,
                        ),
                    )
                    responses.append(response)
                schedule_runners(runners, background)
            except Exception:
                fail_submissions(runners)
                raise
        started([response.task_id for response in responses])
        # Only dedicated workflow workers wait synchronously for child completion.
        for scheduled in background.tasks:
            for runner in cast(list[_TaskRunner], scheduled.args[0]):
                if runner.future is not None:
                    try:
                        runner.future.result()
                    except CancelledError:
                        pass
        completed = [
            _read_job(_job_path(root / project_id, response.task_id))
            for response in responses
        ]
        failed = next((job for job in completed if job["status"] != "succeeded"), None)
        if failed:
            if failed["status"] == "cancelled":
                raise TranscriptionCancelled()
            raise ValueError(str(failed.get("error") or "工作流阶段执行失败"))
        if kind == "export":
            return {
                "entries": [
                    {
                        "outputId": cast(JsonObject, job["result"])["output_id"],
                        "taskId": job["task_id"],
                    }
                    for job in completed
                ]
            }
        return cast(JsonObject, completed[0]["result"])

    def cancel_workflow_child(project_id: str, task_id: str) -> None:
        if _read_job(_job_path(root / project_id, task_id)).get("status") in {
            "pending",
            "running",
        }:
            cancel_export(project_id, task_id)

    api.include_router(
        workflow_router(
            root,
            _read_job,
            _write_job,
            workflow_child,
            cancel_workflow_child,
            workflow_workers,
        )
    )
    return api


app = create_app(Path(os.environ.get("MINICUT_PROJECTS_ROOT", "projects")))


def main() -> None:
    """Run the local-only API server with environment-based configuration."""
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(os.environ.get("MINICUT_API_PORT", "8000")),
    )


__all__ = [
    "ProjectCreateBody",
    "ProjectDetailResponse",
    "PlanDetailResponse",
    "PlanSegmentResponse",
    "PlanVersionsResponse",
    "JumpCutRiskResponse",
    "PreviewClipResponse",
    "PreviewTimelineResponse",
    "ProjectSummaryResponse",
    "TaskResponse",
    "app",
    "create_app",
    "main",
]
