"""Application use cases orchestrating MiniCut domain services."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from minicut.errors import UserInputError
from minicut.project import ProjectManifest, ProjectRepository


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


__all__ = [
    "InitProjectOperation",
    "InitProjectRequest",
    "InitProjectResult",
    "InitProjectUseCase",
]
