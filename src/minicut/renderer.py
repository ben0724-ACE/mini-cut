"""FFmpeg process execution with progress, cancellation, and safe failures."""

import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from queue import Empty, Queue
from threading import Thread
from typing import Protocol, TextIO, cast

from minicut.errors import ProcessingError
from minicut.render_progress import FfmpegProgressEvent, FfmpegProgressParser
from minicut.transcription_task import CancellationToken


class RenderCancelled(ProcessingError):
    """Raised after a cancelled FFmpeg process has been reaped."""


class RenderTimeout(ProcessingError):
    """Raised after an over-time FFmpeg process has been reaped."""


class RenderFailed(ProcessingError):
    """Raised when FFmpeg exits unsuccessfully."""


class RenderProcess(Protocol):
    """Minimal subprocess surface used by the renderer."""

    stdout: TextIO | None
    stderr: TextIO | None

    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    def wait(self, timeout: float | None = None) -> int: ...


RenderProcessLauncher = Callable[[tuple[str, ...]], RenderProcess]
RenderProgressReporter = Callable[[FfmpegProgressEvent], None]


def _launch_process(command: tuple[str, ...]) -> RenderProcess:
    return cast(
        RenderProcess,
        subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ),
    )


def _ignore_progress(event: FfmpegProgressEvent) -> None:
    del event


def _drain(
    stream: TextIO | None,
    destination: list[str],
    line_queue: Queue[str] | None = None,
) -> None:
    if stream is not None:
        for line in stream:
            destination.append(line)
            if line_queue is not None:
                line_queue.put(line)


def _terminate_and_reap(process: RenderProcess) -> None:
    process.terminate()
    try:
        process.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _error_summary(stderr_lines: list[str]) -> str:
    meaningful = [line.strip() for line in stderr_lines if line.strip()]
    if not meaningful:
        return "FFmpeg exited without an error message."
    return " | ".join(meaningful[-4:])[-800:]


@dataclass(slots=True)
class FfmpegRenderer:
    """Execute one FFmpeg argv command and always reap its process."""

    launcher: RenderProcessLauncher = _launch_process
    clock: Callable[[], float] = time.monotonic
    poll_interval_seconds: float = 0.02

    def __post_init__(self) -> None:
        if self.poll_interval_seconds <= 0:
            raise ValueError("render poll interval must be positive")

    def execute(
        self,
        command: tuple[str, ...],
        *,
        timeout_seconds: float,
        cancellation: CancellationToken | None = None,
        on_progress: RenderProgressReporter = _ignore_progress,
    ) -> tuple[FfmpegProgressEvent, ...]:
        """Run FFmpeg, report parsed progress, and map expected failures."""
        if not command:
            raise ValueError("render command must not be empty")
        if timeout_seconds <= 0:
            raise ValueError("render timeout must be positive")
        token = cancellation if cancellation is not None else CancellationToken()
        progress_command = (
            command[0],
            "-progress",
            "pipe:1",
            "-nostats",
            *command[1:],
        )
        try:
            process = self.launcher(progress_command)
        except FileNotFoundError as error:
            raise RenderFailed("FFmpeg executable is not available.") from error

        stdout_lines: list[str] = []
        stderr_lines: list[str] = []
        progress_lines: Queue[str] = Queue()
        parser = FfmpegProgressParser()
        events: list[FfmpegProgressEvent] = []

        def report_available_progress() -> None:
            while True:
                try:
                    line = progress_lines.get_nowait()
                except Empty:
                    return
                event = parser.feed_line(line)
                if event is not None:
                    events.append(event)
                    on_progress(event)

        readers = (
            Thread(
                target=_drain,
                args=(process.stdout, stdout_lines, progress_lines),
                daemon=True,
            ),
            Thread(target=_drain, args=(process.stderr, stderr_lines), daemon=True),
        )
        for reader in readers:
            reader.start()

        started_at = self.clock()
        while process.poll() is None:
            report_available_progress()
            if token.is_cancelled:
                _terminate_and_reap(process)
                for reader in readers:
                    reader.join()
                raise RenderCancelled("Rendering was cancelled.")
            if self.clock() - started_at >= timeout_seconds:
                _terminate_and_reap(process)
                for reader in readers:
                    reader.join()
                raise RenderTimeout("Rendering timed out.")
            time.sleep(self.poll_interval_seconds)

        return_code = process.wait()
        for reader in readers:
            reader.join()
        report_available_progress()
        if return_code != 0:
            raise RenderFailed(f"FFmpeg render failed: {_error_summary(stderr_lines)}")
        return tuple(events)


__all__ = [
    "FfmpegRenderer",
    "RenderCancelled",
    "RenderFailed",
    "RenderProcess",
    "RenderProcessLauncher",
    "RenderProgressReporter",
    "RenderTimeout",
]
