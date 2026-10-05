"""Own task admission, execution, cancellation and explicit recovery."""

import asyncio
import os
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import RLock
from time import monotonic

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
        self, jobs: JobRepository, compute: TaskWorkerPool, exports: TaskWorkerPool
    ) -> None:
        self.jobs, self.compute, self.exports = jobs, compute, exports
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
    ) -> tuple[Job, TaskRunner | None]:
        """Create an owned pending record; repeated requests never own a new runner."""
        with self._lock:
            pending: Job = {
                "task_id": task,
                "owner_pid": os.getpid(),
                "resumable": kind
                in {"transcribe", "highlights", "output-export", "output-preview"},
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
            token = CancellationToken()
            runner = TaskRunner(
                (project, task),
                self.exports
                if kind in {"output-export", "output-preview", "render"}
                else self.compute,
                token,
                lambda: self._run(project, task, token, operation),
            )
            self._active[runner.identity] = runner
            return pending, runner

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
            self.jobs.update(
                project,
                task,
                lambda _: {
                    "status": "succeeded",
                    "result": result,
                    "progress": {
                        "phase": "completed",
                        "elapsed_seconds": round(monotonic() - started, 2),
                    },
                },
            )
        except TranscriptionCancelled:
            self.jobs.update(project, task, lambda _: {"status": "cancelled"})
        except (
            MiniCutError,
            TextModelProviderError,
            ValueError,
            TimeoutError,
        ) as error:
            message = str(error)
            self.jobs.update(
                project, task, lambda _: {"status": "failed", "error": message}
            )
        except Exception:
            self.jobs.update(
                project,
                task,
                lambda _: {
                    "status": "failed",
                    "error": "Task failed; completed stages are retained for recovery",
                },
            )

    def _settle(self, runner: TaskRunner) -> None:
        with self._lock:
            if self._active.get(runner.identity) is runner:
                self._active.pop(runner.identity)

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
            runner.token.cancel()

            def cancelled() -> None:
                self.jobs.update(project, task, lambda _: {"status": "cancelled"})

            if runner.future is None:
                cancelled()
            else:
                runner.pool.cancel(runner.future, on_cancel=cancelled)
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
        for pool in (self.compute, self.exports):
            pool.shutdown()
