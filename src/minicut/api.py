"""Local HTTP API that adapts web schemas to MiniCut application services."""

import json
import mimetypes
import os
from collections.abc import Callable, Iterator
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Annotated, Self, cast
from uuid import uuid4

import uvicorn
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request, status
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
from minicut.edit_plan import EditIntensity
from minicut.errors import MiniCutError
from minicut.highlight_brief import HighlightBrief, HighlightPreset
from minicut.highlight_service import generate_highlights, read_highlights
from minicut.importer import import_media
from minicut.media import classify_media
from minicut.output_repository import OutputCollectionRepository
from minicut.project import ProjectRepository

ProjectId = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")]
SafeFileName = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")]


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
    count: int = Field(ge=1, le=10)
    min_ms: int | None = Field(default=None, gt=0)
    max_ms: int | None = Field(default=None, gt=0)
    hook_ms: int | None = Field(default=None, gt=0)
    instructions: str = Field(default="", max_length=12000)
    max_source_overlap: float = Field(default=0.3, ge=0, le=1)

    def brief(self) -> HighlightBrief:
        return HighlightBrief(**self.model_dump(exclude={"asset_id"}))

    @model_validator(mode="after")
    def valid_brief(self) -> Self:
        self.brief()
        return self


class HighlightSelectionBody(BaseModel):
    output_ids: list[str]


class RenderTaskBody(BaseModel):
    asset_id: str
    output_name: SafeFileName
    timeout_seconds: float = Field(default=600, gt=0)


class TaskResponse(BaseModel):
    task_id: str
    kind: str
    status: str
    result: dict[str, object] | None = None
    error: str | None = None


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
        try:
            with path.open("x", encoding="utf-8") as output:
                json.dump(payload, output, ensure_ascii=False)
                output.write("\n")
            return
        except FileExistsError:
            raise
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
        return cast(dict[str, object], value)
    except (OSError, TypeError, UnicodeError, ValueError) as error:
        raise HTTPException(status_code=404, detail="Task does not exist") from error


def _task_response(payload: dict[str, object]) -> TaskResponse:
    return TaskResponse.model_validate(payload)


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
    api = FastAPI(title="MiniCut local API", version="0.1.0")

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

    def submit_task(
        project_id: str,
        task_id: str,
        kind: str,
        request_data: dict[str, object],
        background_tasks: BackgroundTasks,
        operation: Callable[[], dict[str, object]],
    ) -> TaskResponse:
        project_directory = root / project_id
        inspect(project_id)
        path = _job_path(project_directory, task_id)
        pending: dict[str, object] = {
            "task_id": task_id,
            "kind": kind,
            "status": "pending",
            "request": request_data,
            "result": None,
            "error": None,
        }
        try:
            _write_job(path, pending, create=True)
        except FileExistsError:
            existing = _read_job(path)
            if existing.get("kind") != kind or existing.get("request") != request_data:
                raise HTTPException(
                    status_code=409,
                    detail="Idempotency key is already used by another request",
                ) from None
            return _task_response(existing)

        def run() -> None:
            running = {**pending, "status": "running"}
            _write_job(path, running)
            try:
                result = operation()
                _write_job(
                    path,
                    {**running, "status": "succeeded", "result": result},
                )
            except MiniCutError as error:
                _write_job(
                    path,
                    {**running, "status": "failed", "error": str(error)},
                )
            except Exception:
                _write_job(
                    path,
                    {**running, "status": "failed", "error": "Task failed"},
                )

        background_tasks.add_task(run)
        return _task_response(pending)

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
        manifest = ProjectRepository(root / project_id).read()
        if not any(asset.asset_id == body.asset_id for asset in manifest.assets):
            raise HTTPException(404, "Asset does not exist")
        if not (
            root / project_id / ".minicut/transcripts" / f"{body.asset_id}.json"
        ).is_file():
            raise HTTPException(400, "Transcription is required")
        return submit_task(
            project_id,
            idempotency_key,
            "highlights",
            body.model_dump(mode="json"),
            background_tasks,
            lambda: highlights(
                root / project_id,
                body.asset_id,
                f"highlights-{uuid4().hex}",
                body.brief(),
            ),
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
