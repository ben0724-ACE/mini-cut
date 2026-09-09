import subprocess
import unittest
from io import StringIO
from typing import TextIO

from minicut.render_progress import FfmpegProgressEvent
from minicut.renderer import (
    FfmpegRenderer,
    RenderCancelled,
    RenderFailed,
    RenderTimeout,
)
from minicut.transcription_task import CancellationToken


class FakeProcess:
    def __init__(
        self,
        *,
        return_code: int = 0,
        stdout: str = "",
        stderr: str = "",
        running_polls: int = 0,
        ignore_terminate: bool = False,
    ) -> None:
        self.return_code = return_code
        self.stdout: TextIO | None = StringIO(stdout)
        self.stderr: TextIO | None = StringIO(stderr)
        self.running_polls = running_polls
        self.ignore_terminate = ignore_terminate
        self.terminated = False
        self.killed = False
        self.wait_calls: list[float | None] = []

    def poll(self) -> int | None:
        if self.killed or self.terminated and not self.ignore_terminate:
            return -9
        if self.running_polls > 0:
            self.running_polls -= 1
            return None
        return self.return_code

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls.append(timeout)
        if timeout is not None and self.ignore_terminate and not self.killed:
            raise subprocess.TimeoutExpired("ffmpeg", timeout)
        return -9 if self.terminated or self.killed else self.return_code


class CapturingLauncher:
    def __init__(self, process: FakeProcess) -> None:
        self.process = process
        self.command: tuple[str, ...] | None = None

    def __call__(self, command: tuple[str, ...]) -> FakeProcess:
        self.command = command
        return self.process


class FfmpegRendererTest(unittest.TestCase):
    def test_executes_with_progress_protocol_and_reports_events(self) -> None:
        process = FakeProcess(
            stdout="out_time_us=500000\nprogress=continue\n"
            "out_time_us=1000000\nprogress=end\n"
        )
        launcher = CapturingLauncher(process)
        reported: list[FfmpegProgressEvent] = []

        events = FfmpegRenderer(launcher=launcher).execute(
            ("ffmpeg", "-i", "file:///input.mov", "file:///output.mp4"),
            timeout_seconds=5,
            on_progress=reported.append,
        )

        assert launcher.command is not None
        self.assertEqual(launcher.command[1:4], ("-progress", "pipe:1", "-nostats"))
        self.assertEqual(events, tuple(reported))
        self.assertEqual([event.out_time_ms for event in events], [500, 1_000])
        self.assertEqual(process.wait_calls, [None])

    def test_cancellation_terminates_and_reaps_process(self) -> None:
        process = FakeProcess(running_polls=10)
        launcher = CapturingLauncher(process)
        token = CancellationToken()
        token.cancel()

        with self.assertRaisesRegex(RenderCancelled, "cancelled"):
            FfmpegRenderer(launcher=launcher).execute(
                ("ffmpeg", "file:///output.mp4"),
                timeout_seconds=5,
                cancellation=token,
            )

        self.assertTrue(process.terminated)
        self.assertEqual(process.wait_calls, [1.0])

    def test_timeout_escalates_to_kill_and_reaps_process(self) -> None:
        process = FakeProcess(running_polls=10, ignore_terminate=True)
        launcher = CapturingLauncher(process)
        times = iter((0.0, 2.0))

        with self.assertRaisesRegex(RenderTimeout, "timed out"):
            FfmpegRenderer(launcher=launcher, clock=lambda: next(times)).execute(
                ("ffmpeg", "file:///output.mp4"),
                timeout_seconds=1,
            )

        self.assertTrue(process.terminated)
        self.assertTrue(process.killed)
        self.assertEqual(process.wait_calls, [1.0, None])

    def test_nonzero_exit_keeps_bounded_stderr_context(self) -> None:
        stderr = "\n".join(f"line {index}" for index in range(10))
        process = FakeProcess(return_code=1, stderr=stderr)

        with self.assertRaises(RenderFailed) as raised:
            FfmpegRenderer(launcher=CapturingLauncher(process)).execute(
                ("ffmpeg", "file:///output.mp4"),
                timeout_seconds=5,
            )

        message = str(raised.exception)
        self.assertIn("line 9", message)
        self.assertIn("line 6", message)
        self.assertNotIn("line 5", message)
        self.assertLessEqual(len(message), 850)
        self.assertEqual(process.wait_calls, [None])

    def test_missing_executable_is_mapped(self) -> None:
        def missing_launcher(command: tuple[str, ...]) -> FakeProcess:
            del command
            raise FileNotFoundError

        with self.assertRaisesRegex(RenderFailed, "not available"):
            FfmpegRenderer(launcher=missing_launcher).execute(
                ("ffmpeg", "file:///output.mp4"),
                timeout_seconds=5,
            )


if __name__ == "__main__":
    unittest.main()
