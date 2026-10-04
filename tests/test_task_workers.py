import asyncio
from threading import Event

import pytest

from minicut.task_workers import TaskQueueFull, TaskWorkerPool, wait_for_task


def test_queue_admission_cancel_and_failure_recovery() -> None:
    pool = TaskWorkerPool(1, capacity=1, name="test-tasks")
    started, release = Event(), Event()
    calls: list[str] = []

    def blocking() -> None:
        started.set()
        assert release.wait(3)

    try:
        running = pool.submit(blocking)
        assert started.wait(3)
        waiting = pool.submit(lambda: calls.append("cancelled"))
        with pytest.raises(TaskQueueFull):
            pool.submit(lambda: calls.append("rejected"))
        assert pool.cancel(waiting)
        assert waiting.cancelled()
        assert not pool.cancel(running)

        def fail() -> None:
            raise ValueError("operation failed")

        failed = pool.submit(fail)
        release.set()
        running.result(timeout=3)
        with pytest.raises(ValueError, match="operation failed"):
            failed.result(timeout=3)
        pool.submit(lambda: calls.append("next")).result(timeout=3)
        assert calls == ["next"]
        asyncio.run(wait_for_task(waiting))
    finally:
        release.set()
        pool.shutdown()
    with pytest.raises(RuntimeError, match="closed"):
        pool.submit(lambda: None)


def test_disconnect_does_not_cancel_accepted_work() -> None:
    pool = TaskWorkerPool(1, name="test-disconnect")
    started, release, completed = Event(), Event(), Event()

    def blocking() -> None:
        started.set()
        assert release.wait(3)
        completed.set()

    async def run() -> None:
        future = pool.submit(blocking)
        assert await asyncio.to_thread(started.wait, 3)
        observer = asyncio.create_task(wait_for_task(future))
        await asyncio.sleep(0)
        observer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await observer
        assert not future.cancelled()
        release.set()
        await wait_for_task(future)
        assert completed.is_set()

    try:
        asyncio.run(run())
    finally:
        release.set()
        pool.shutdown()


def test_full_queue_rejects_entire_batch() -> None:
    pool = TaskWorkerPool(1, capacity=2, name="test-batch")
    started, release = Event(), Event()
    calls: list[str] = []

    def blocking() -> None:
        started.set()
        assert release.wait(3)

    try:
        pool.submit(blocking)
        assert started.wait(3)
        pool.submit(lambda: calls.append("accepted"))
        with pytest.raises(TaskQueueFull):
            pool.submit_many(
                [lambda: calls.append("first"), lambda: calls.append("second")]
            )
        release.set()
    finally:
        release.set()
        pool.shutdown()
    assert calls == ["accepted"]
