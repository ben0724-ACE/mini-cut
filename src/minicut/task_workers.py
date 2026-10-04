"""Bounded local task queues with workers independent of HTTP's thread pool."""

import asyncio
from collections import deque
from collections.abc import Callable
from concurrent.futures import Future
from threading import Condition, Thread


class TaskQueueFull(Exception):
    """The worker queue cannot accept another task without waiting."""


class TaskWorkerPool:
    """Run synchronous operations on fixed workers; admission never blocks."""

    def __init__(self, workers: int, *, capacity: int = 64, name: str) -> None:
        if workers < 1 or capacity < 1:
            raise ValueError("Worker count and queue capacity must be positive")
        self._workers = workers
        self._capacity = capacity
        self._name = name
        self._condition = Condition()
        self._queue: deque[tuple[Future[None], Callable[[], None]]] = deque()
        self._threads: list[Thread] = []
        self._closed = False

    def submit(self, operation: Callable[[], None]) -> Future[None]:
        return self.submit_many([operation])[0]

    def submit_many(self, operations: list[Callable[[], None]]) -> list[Future[None]]:
        """Admit a batch together so a full queue cannot leave half submitted."""
        with self._condition:
            if self._closed:
                raise RuntimeError("Task worker pool is closed")
            if len(self._queue) + len(operations) > self._capacity:
                raise TaskQueueFull("后台任务队列已满，请稍后重试")
            if not operations:
                return []
            for index in range(len(self._threads), self._workers):
                thread = Thread(
                    target=self._work,
                    name=f"{self._name}-{index}",
                    daemon=True,
                )
                thread.start()
                self._threads.append(thread)
            futures: list[Future[None]] = [Future() for _ in operations]
            self._queue.extend(zip(futures, operations, strict=True))
            self._condition.notify_all()
            return futures

    def cancel(
        self, future: Future[None], *, on_cancel: Callable[[], None] | None = None
    ) -> bool:
        """Remove a waiting task immediately, freeing its queue capacity."""
        with self._condition:
            for entry in self._queue:
                if entry[0] is future:
                    if on_cancel is not None:
                        on_cancel()
                    self._queue.remove(entry)
                    return future.cancel()
            return False

    def shutdown(self) -> None:
        """Drain admitted work and join workers when the API shuts down."""
        with self._condition:
            self._closed = True
            self._condition.notify_all()
        for thread in self._threads:
            thread.join()

    def _work(self) -> None:
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._queue or self._closed)
                if not self._queue:
                    return
                future, operation = self._queue.popleft()
                if not future.set_running_or_notify_cancel():
                    continue
            try:
                operation()
            except BaseException as error:
                future.set_exception(error)
            else:
                future.set_result(None)


async def wait_for_task(future: Future[None]) -> None:
    """Observe completion without borrowing a shared HTTP worker thread."""
    try:
        await asyncio.shield(asyncio.wrap_future(future))
    except asyncio.CancelledError:
        if not future.cancelled():
            raise
