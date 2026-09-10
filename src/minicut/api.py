"""Local HTTP API that adapts web schemas to MiniCut application services."""

import json
import os
from collections.abc import Callable
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Annotated, cast

import uvicorn
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

from minicut.application import (
    InitProjectOperation,
    InitProjectRequest,
    InitProjectUseCase,
    InspectOperation,
    InspectProjectUseCase,
    InspectRequest,
    InspectResult,
    PlanOperation,
    PlanProjectUseCase,
    PlanRequest,
    RenderOperation,
    RenderProjectUseCase,
    RenderRequest,
    TranscribeOperation,
    TranscribeProjectUseCase,
    TranscribeRequest,
)
from minicut.edit_plan import EditIntensity
from minicut.errors import MiniCutError

ProjectId = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")]
SafeFileName = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")]


class ProjectCreateBody(BaseModel):
    """HTTP input for creating one project below the configured root."""

    project_id: ProjectId


class ProjectSummaryResponse(BaseModel):
    """Stable web representation of one local project."""

    project_id: str
    asset_count: int


class ProjectDetailResponse(ProjectSummaryResponse):
    """Project summary with identifiers needed for subsequent API calls."""

    asset_ids: list[str]


class TranscribeTaskBody(BaseModel):
    source_path: str
    provider: str = Field(pattern=r"^(mlx|whisper)$")
    model: str
    language: str = "zh"


class PlanTaskBody(BaseModel):
    asset_id: str
    target_duration_ms: int = Field(gt=0)
    intensity: EditIntensity = EditIntensity.BALANCED
    style: str = "concise"
    planner: str = Field(default="rule", pattern=r"^(rule|deepseek)$")


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


def create_app(
    projects_root: Path,
    *,
    init_project: InitProjectOperation | None = None,
    inspect_project: InspectOperation | None = None,
    transcribe: TranscribeOperation | None = None,
    plan: PlanOperation | None = None,
    render: RenderOperation | None = None,
) -> FastAPI:
    """Create an API instance bound to one local projects directory."""
    root = projects_root.absolute()
    initializer = init_project or InitProjectUseCase()
    inspector = inspect_project or InspectProjectUseCase()
    transcriber = transcribe or TranscribeProjectUseCase()
    planner = plan or PlanProjectUseCase()
    renderer = render or RenderProjectUseCase()
    api = FastAPI(title="MiniCut local API", version="0.1.0")

    def inspect(project_id: str) -> InspectResult:
        try:
            return inspector.execute(InspectRequest(root / project_id))
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
        status_code=status.HTTP_201_CREATED,
    )
    def create_project(  # pyright: ignore[reportUnusedFunction]
        body: ProjectCreateBody,
    ) -> ProjectDetailResponse:
        try:
            initializer.execute(
                InitProjectRequest(root / body.project_id, body.project_id)
            )
        except MiniCutError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        result = inspect(body.project_id)
        return ProjectDetailResponse(
            project_id=result.project_id,
            asset_count=len(result.asset_ids),
            asset_ids=list(result.asset_ids),
        )

    @api.get("/api/projects", response_model=list[ProjectSummaryResponse])
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
                )
            )
        return projects

    @api.get("/api/projects/{project_id}", response_model=ProjectDetailResponse)
    def get_project(  # pyright: ignore[reportUnusedFunction]
        project_id: ProjectId,
    ) -> ProjectDetailResponse:
        result = inspect(project_id)
        return ProjectDetailResponse(
            project_id=result.project_id,
            asset_count=len(result.asset_ids),
            asset_ids=list(result.asset_ids),
        )

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
        request_data = body.model_dump(mode="json")

        def operation() -> dict[str, object]:
            result = transcriber.execute(
                TranscribeRequest(
                    root / project_id,
                    Path(body.source_path),
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
    "ProjectSummaryResponse",
    "TaskResponse",
    "app",
    "create_app",
    "main",
]
