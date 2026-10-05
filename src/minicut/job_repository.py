"""Durable job records and serialized read/modify/write operations."""

import json
from collections.abc import Callable
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Protocol, cast

from minicut.errors import UserInputError
from minicut.platform_support import process_alive
from minicut.project_mutation import project_mutation_lock

Job = dict[str, object]


class JobNotFound(UserInputError):
    pass


class JobWriter(Protocol):
    def __call__(self, path: Path, payload: Job, *, create: bool = False) -> None: ...


def job_path(project_directory: Path, task_id: str) -> Path:
    return project_directory / ".minicut/jobs" / f"{task_id}.json"


def _directory(path: Path) -> Path:
    return (
        path.parents[2]
        if path.parent.name == "jobs" and path.parent.parent.name == ".minicut"
        else path.parent
    )


def write_job(path: Path, payload: Job, *, create: bool = False) -> None:
    with project_mutation_lock(_directory(path)):
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


def read_job(path: Path) -> Job:
    with project_mutation_lock(_directory(path)):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("job is not an object")
            job = cast(Job, value)
            if job.get("status") in ("running", "pending"):
                pid = job.get("owner_pid")
                if not (type(pid) is int and pid > 0 and process_alive(pid)):
                    job.update(
                        status="failed",
                        error="服务已重启，任务已中断；可恢复已保存的阶段。",
                        resumable=True,
                    )
            return job
        except (OSError, TypeError, UnicodeError, ValueError) as error:
            raise JobNotFound("Task does not exist") from error


class JobRepository:
    def __init__(
        self,
        root: Path,
        *,
        reader: Callable[[Path], Job] = read_job,
        writer: JobWriter = write_job,
    ) -> None:
        self.root, self.reader, self.writer = root, reader, writer

    def read(self, project: str, task: str) -> Job:
        return self.reader(job_path(self.root / project, task))

    def create(self, project: str, task: str, job: Job) -> None:
        self.writer(job_path(self.root / project, task), job, create=True)

    def update(self, project: str, task: str, changes: Callable[[Job], Job]) -> Job:
        with project_mutation_lock(self.root / project):
            job = self.read(project, task)
            job.update(changes(job))
            self.writer(job_path(self.root / project, task), job)
            return job
