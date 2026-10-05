"""Own task admission, execution, cancellation and explicit recovery."""

import asyncio
import os
from collections.abc import Callable
from concurrent.futures import CancelledError, Future
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import RLock
from time import monotonic
from typing import cast

from minicut.errors import MiniCutError
from minicut.job_repository import Job, JobRepository
from minicut.llm_provider import TextModelProviderError
from minicut.task_workers import TaskWorkerPool, wait_for_task
from minicut.transcription_task import CancellationToken, TranscriptionCancelled


class TaskConflict(MiniCutError):
    pass


@dataclass
class TaskRunner:
    identity: tuple[str, str]
    pool: TaskWorkerPool
    token: CancellationToken
    run: Callable[[], None]
    future: Future[None] | None = None


class TaskExecutor:
    def __init__(
        self,
        jobs: JobRepository,
        compute: TaskWorkerPool,
        exports: TaskWorkerPool,
        workflows: TaskWorkerPool | None = None,
    ) -> None:
        self.jobs, self.compute, self.exports = jobs, compute, exports
        self.workflows = workflows
        self._lock = RLock()
        self._active: dict[tuple[str, str], TaskRunner] = {}

    def existing(self, project: str, task: str, kind: str, request: Job) -> Job:
        job = self.jobs.read(project, task)
        if job.get("kind") != kind or job.get("request") != request:
            raise TaskConflict("Idempotency key is already used by another request")
        return job

    def prepare(
        self,
        project: str,
        task: str,
        kind: str,
        request: Job,
        operation: Callable[[CancellationToken], Job],
        *,
        generation_config: Job | None = None,
        metadata: Job | None = None,
    ) -> tuple[Job, TaskRunner | None]:
        """Create an owned pending record; repeated requests never own a new runner."""
        with self._lock:
            if kind == "workflow" and self.workflows is None:
                raise ValueError("Workflow worker queue is not configured")
            pending: Job = {
                **(metadata or {}),
                "task_id": task,
                "owner_pid": os.getpid(),
                "resumable": kind
                in {
                    "transcribe",
                    "highlights",
                    "output-export",
                    "output-preview",
                    "workflow",
                },
                "kind": kind,
                "status": "pending",
                "request": request,
                "result": None,
                "error": None,
            }
            if kind == "highlights":
                pending.update(
                    created_at=datetime.now(UTC).isoformat(),
                    generation_config=generation_config,
                )
            try:
                self.jobs.create(project, task, pending)
            except FileExistsError:
                return self.existing(project, task, kind, request), None
            runner = self._runner(project, task, kind, operation)
            return pending, runner

    def _runner(
        self,
        project: str,
        task: str,
        kind: str,
        operation: Callable[[CancellationToken], Job],
    ) -> TaskRunner:
        pool = (
            self.exports
            if kind in {"output-export", "output-preview", "render"}
            else self.compute
        )
        if kind == "workflow":
            if self.workflows is None:
                raise ValueError("Workflow worker queue is not configured")
            pool = self.workflows
        token = CancellationToken()
        runner = TaskRunner(
            (project, task),
            pool,
            token,
            lambda: self._run(project, task, token, operation),
        )
        self._active[runner.identity] = runner
        return runner

    def restart_workflow(
        self, project: str, task: str, operation: Callable[[CancellationToken], Job]
    ) -> tuple[Job, TaskRunner | None]:
        """Reuse the coordinator identity and its saved stages, with one owner."""
        with self._lock:
            job = self.jobs.read(project, task)
            if job.get("kind") != "workflow":
                raise TaskConflict("工作流任务不存在")
            active = self._active.get((project, task))
            if active is not None:
                if active.future is None or not active.future.done():
                    return job, None
                self._settle(active)
            if job.get("status") not in {"failed", "cancelled"}:
                raise TaskConflict("只有失败或取消的工作流可以继续")
            pending = self.jobs.update(
                project,
                task,
                lambda _: {
                    "status": "pending",
                    "error": None,
                    "cancel_requested": False,
                    "owner_pid": os.getpid(),
                },
            )
            return pending, self._runner(project, task, "workflow", operation)

    def _terminal(self, project: str, task: str, changes: Job) -> None:
        def patch(job: Job) -> Job:
            fields = dict(changes)
            if job.get("kind") == "workflow":
                fields["child_task_ids"] = []
                if fields["status"] == "succeeded":
                    fields["phase"] = "completed"
            return fields

        self.jobs.update(project, task, patch)

    def _run(
        self,
        project: str,
        task: str,
        token: CancellationToken,
        operation: Callable[[CancellationToken], Job],
    ) -> None:
        started = monotonic()
        try:
            self.jobs.update(project, task, lambda _: {"status": "running"})
            token.raise_if_cancelled()
            result = operation(token)
            self._terminal(
                project,
                task,
                {
                    "status": "succeeded",
                    "result": result,
                    "progress": {
                        "phase": "completed",
                        "elapsed_seconds": round(monotonic() - started, 2),
                    },
                },
            )
        except TranscriptionCancelled:
            self._terminal(project, task, {"status": "cancelled"})
        except (
            MiniCutError,
            TextModelProviderError,
            ValueError,
            TimeoutError,
        ) as error:
            message = str(error)
            self._terminal(project, task, {"status": "failed", "error": message})
        except Exception:
            self._terminal(
                project,
                task,
                {
                    "status": "failed",
                    "error": "Task failed; completed stages are retained for recovery",
                },
            )

    def _settle(self, runner: TaskRunner) -> None:
        with self._lock:
            if self._active.get(runner.identity) is runner:
                self._active.pop(runner.identity)

    def is_active(self, project: str, task: str) -> bool:
        with self._lock:
            runner = self._active.get((project, task))
            if runner is None:
                return False
            if runner.future is not None and runner.future.done():
                self._settle(runner)
                return False
            return True

    def abort(self, runners: list[TaskRunner]) -> None:
        """Settle every newly prepared task even when another cleanup fails."""
        first_error: Exception | None = None
        with self._lock:
            try:
                for runner in runners:
                    try:
                        job = self.jobs.update(
                            *runner.identity,
                            lambda job: (
                                {
                                    "status": "failed",
                                    "error": "任务提交或调度失败；可恢复已保存的任务。",
                                }
                                if job.get("status") == "pending"
                                else {}
                            ),
                        )
                        if (
                            job.get("status") in {"failed", "cancelled"}
                            and runner.future is None
                        ):
                            self._settle(runner)
                    except Exception as error:
                        if first_error is None:
                            first_error = error
            finally:
                runners.clear()
        if first_error is not None:
            raise first_error

    @staticmethod
    async def observe(runners: list[TaskRunner]) -> None:
        await asyncio.gather(
            *(
                wait_for_task(runner.future)
                for runner in runners
                if runner.future is not None
            )
        )

    def schedule(
        self, runners: list[TaskRunner], register: Callable[[list[TaskRunner]], None]
    ) -> None:
        """Admit one queue's batch and register cancellation handles together."""
        if not runners:
            return
        with self._lock:
            try:
                register(runners)
                waiting = [
                    runner for runner in runners if not runner.token.is_cancelled
                ]
                if waiting and any(
                    runner.pool is not waiting[0].pool for runner in waiting
                ):
                    raise ValueError("A task batch must use one worker queue")
                futures = (
                    waiting[0].pool.submit_many([runner.run for runner in waiting])
                    if waiting
                    else []
                )
                for runner, future in zip(waiting, futures, strict=True):
                    runner.future = future
                    future.add_done_callback(
                        lambda _, runner=runner: self._settle(runner)
                    )
                for runner in runners:
                    if runner.token.is_cancelled and runner.future is None:
                        runner.future = Future()
                        runner.future.cancel()
                        self._settle(runner)
            except Exception:
                self.abort(runners)
                raise

    def cancel(self, project: str, task: str) -> Job:
        with self._lock:
            job = self.jobs.read(project, task)
            if job.get("status") not in {"pending", "running"}:
                return job
            runner = self._active.get((project, task))
            if runner is None:
                raise TaskConflict(
                    "This task cannot be cancelled by this server; it may predate a restart"
                )
            if job.get("kind") == "workflow":
                job = self.jobs.update(
                    project, task, lambda _: {"cancel_requested": True}
                )
            runner.token.cancel()

            def cancelled() -> None:
                self._terminal(project, task, {"status": "cancelled"})

            if runner.future is None:
                cancelled()
            else:
                runner.pool.cancel(runner.future, on_cancel=cancelled)
            if job.get("kind") == "workflow":
                children = job.get("child_task_ids", [])
                if isinstance(children, list):
                    for child in cast(list[object], children):
                        if isinstance(child, str):
                            self.cancel(project, child)
            return self.jobs.read(project, task)

    def progress(self, project: str, task: str, done: int, total: int) -> None:
        self.jobs.update(
            project,
            task,
            lambda job: (
                {
                    "progress": {
                        "completed": done,
                        "total": total,
                        "phase": "transcription",
                    }
                }
                if job.get("status") in {"pending", "running"}
                else {}
            ),
        )

    def resume(self, project: str, task: str, dispatch: Callable[[Job], Job]) -> Job:
        with self._lock:
            job = self.jobs.read(project, task)
            existing = job.get("resumed_task_id")
            if isinstance(existing, str):
                return self.jobs.read(project, existing)
            if job.get("status") not in {"failed", "cancelled"}:
                raise TaskConflict(
                    "Only interrupted, failed or cancelled tasks can be resumed"
                )
            response = dispatch(job)
            self.jobs.update(
                project, task, lambda _: {"resumed_task_id": response["task_id"]}
            )
            return response

    def shutdown(self) -> None:
        # Coordinators finish their children before the child queues close.
        if self.workflows is not None:
            self.workflows.shutdown()
        for pool in (self.compute, self.exports):
            pool.shutdown()

    def wait(self, project: str, tasks: list[str]) -> None:
        """Only dedicated coordinators wait synchronously; release ownership first."""
        with self._lock:
            futures = [
                runner.future
                for task in tasks
                if (runner := self._active.get((project, task))) is not None
                and runner.future is not None
            ]
        for future in futures:
            try:
                future.result()
            except CancelledError:
                pass
