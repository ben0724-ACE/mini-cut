from collections.abc import Callable, Generator
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from threading import Event
from typing import cast

import pytest

from minicut.job_repository import Job, JobRepository, write_job
from minicut.task_executor import TaskExecutor, TaskRunner
from minicut.task_workers import TaskWorkerPool
from minicut.transcription_task import CancellationToken


@pytest.fixture
def executor(tmp_path: Path) -> Generator[TaskExecutor, None, None]:
    executor = TaskExecutor(
        JobRepository(tmp_path),
        TaskWorkerPool(1, capacity=1, name="test-compute"),
        TaskWorkerPool(1, capacity=1, name="test-export"),
    )
    try:
        yield executor
    finally:
        executor.shutdown()


def prepare(
    executor: TaskExecutor, task: str, operation: Callable[[CancellationToken], Job]
) -> TaskRunner:
    _, runner = executor.prepare(
        "demo", task, "transcribe", {"model": "saved"}, operation
    )
    assert runner is not None
    return runner


def test_cancel_before_batch_admission_never_runs_or_consumes_a_slot(
    executor: TaskExecutor,
) -> None:
    calls: list[str] = []

    def operation(token: CancellationToken) -> Job:
        calls.append("operation")
        return {"completed": True}

    runner = prepare(executor, "cancelled", operation)
    assert executor.cancel("demo", "cancelled")["status"] == "cancelled"
    executor.schedule([runner], lambda _: None)
    assert runner.future is not None and runner.future.cancelled()
    repeated, owned = executor.prepare(
        "demo", "cancelled", "transcribe", {"model": "saved"}, operation
    )
    assert repeated["status"] == "cancelled" and owned is None
    next_runner = prepare(executor, "next", operation)
    executor.schedule([next_runner], lambda _: None)
    assert next_runner.future is not None
    next_runner.future.result(timeout=3)
    assert calls == ["operation"]
    # A delayed progress callback must not replace the final completion phase.
    executor.progress("demo", "next", 1, 2)
    saved = executor.jobs.read("demo", "next")
    assert saved["status"] == "succeeded"
    assert cast(Job, saved["progress"])["phase"] == "completed"


def test_cancel_between_queue_admission_and_future_registration_is_not_lost(
    executor: TaskExecutor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started, release, admitted, finish_admission, cancelling = (
        Event() for _ in range(5)
    )
    calls: list[str] = []

    def block(token: CancellationToken) -> Job:
        started.set()
        assert release.wait(5)
        return {}

    def waiting(token: CancellationToken) -> Job:
        calls.append("waiting")
        return {}

    first = prepare(executor, "first", block)
    executor.schedule([first], lambda _: None)
    try:
        assert started.wait(3)
        runner = prepare(executor, "waiting", waiting)
        submit = TaskWorkerPool.submit_many

        def pause_submit(
            pool: TaskWorkerPool, operations: list[Callable[[], None]]
        ) -> list[Future[None]]:
            futures = submit(pool, operations)
            admitted.set()
            assert finish_admission.wait(5)
            return futures

        def cancel() -> Job:
            cancelling.set()
            return executor.cancel("demo", "waiting")

        with monkeypatch.context() as patch:
            patch.setattr(TaskWorkerPool, "submit_many", pause_submit)
            with ThreadPoolExecutor(max_workers=2) as threads:
                scheduling = threads.submit(executor.schedule, [runner], lambda _: None)
                try:
                    assert admitted.wait(3)
                    cancellation = threads.submit(cancel)
                    assert cancelling.wait(3)
                    with pytest.raises(TimeoutError):
                        cancellation.result(timeout=0.2)
                finally:
                    finish_admission.set()
                scheduling.result(timeout=3)
                assert cancellation.result(timeout=3)["status"] == "cancelled"
        assert runner.future is not None and runner.future.cancelled()
        next_runner = prepare(executor, "next", waiting)
        executor.schedule([next_runner], lambda _: None)
        release.set()
        assert next_runner.future is not None
        next_runner.future.result(timeout=3)
        assert calls == ["waiting"]
    finally:
        finish_admission.set()
        release.set()


def test_job_mutations_preserve_other_concurrent_fields(tmp_path: Path) -> None:
    repository = JobRepository(tmp_path)
    repository.create(
        "demo", "job", {"status": "failed", "request": {"model": "saved"}}
    )
    writing, release, updating = (Event() for _ in range(3))

    def pause_write(path: Path, payload: Job, *, create: bool = False) -> None:
        writing.set()
        assert release.wait(5)
        write_job(path, payload, create=create)

    first = JobRepository(tmp_path, writer=pause_write)
    second = JobRepository(tmp_path / ".." / tmp_path.name)

    def update_second() -> Job:
        updating.set()
        return second.update("demo", "job", lambda _: {"resumed_task_id": "resume"})

    with ThreadPoolExecutor(max_workers=2) as threads:
        progress = threads.submit(
            first.update, "demo", "job", lambda _: {"progress": {"completed": 1}}
        )
        try:
            assert writing.wait(3)
            resumed = threads.submit(update_second)
            assert updating.wait(3)
            with pytest.raises(TimeoutError):
                resumed.result(timeout=0.2)
        finally:
            release.set()
        progress.result(timeout=3)
        resumed.result(timeout=3)
    saved = repository.read("demo", "job")
    assert saved == {
        "status": "failed",
        "request": {"model": "saved"},
        "progress": {"completed": 1},
        "resumed_task_id": "resume",
    }
