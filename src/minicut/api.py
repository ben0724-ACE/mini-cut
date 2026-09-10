"""Local HTTP API that adapts web schemas to MiniCut application services."""

import os
from pathlib import Path
from typing import Annotated

import uvicorn
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field

from minicut.application import (
    InitProjectOperation,
    InitProjectRequest,
    InitProjectUseCase,
    InspectOperation,
    InspectProjectUseCase,
    InspectRequest,
    InspectResult,
)
from minicut.errors import MiniCutError

ProjectId = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")]


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


def create_app(
    projects_root: Path,
    *,
    init_project: InitProjectOperation | None = None,
    inspect_project: InspectOperation | None = None,
) -> FastAPI:
    """Create an API instance bound to one local projects directory."""
    root = projects_root.absolute()
    initializer = init_project or InitProjectUseCase()
    inspector = inspect_project or InspectProjectUseCase()
    api = FastAPI(title="MiniCut local API", version="0.1.0")

    def inspect(project_id: str) -> InspectResult:
        try:
            return inspector.execute(InspectRequest(root / project_id))
        except MiniCutError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

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
    "app",
    "create_app",
    "main",
]
