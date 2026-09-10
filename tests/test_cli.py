import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from minicut.application import (
    InitProjectRequest,
    InitProjectResult,
    PlanRequest,
    PlanResult,
    RenderRequest,
    RenderResult,
    TranscribeRequest,
    TranscribeResult,
)
from minicut.cli import CliServices, main, run_cli
from minicut.edit_plan import EditIntensity
from minicut.errors import UserInputError


class CommandLineHelpTest(unittest.TestCase):
    def test_help_exits_successfully_and_describes_the_product(self) -> None:
        output = StringIO()

        with redirect_stdout(output), self.assertRaises(SystemExit) as exit_context:
            main(["--help"])

        self.assertEqual(exit_context.exception.code, 0)
        self.assertIn("usage: minicut", output.getvalue())
        self.assertIn("rough-cutting", output.getvalue())


class CommandLineErrorTest(unittest.TestCase):
    @staticmethod
    def fail_with_expected_error() -> int:
        raise UserInputError("The media path is invalid.")

    def test_expected_error_hides_the_traceback_by_default(self) -> None:
        error_output = StringIO()

        exit_code = run_cli(
            self.fail_with_expected_error,
            error_stream=error_output,
        )

        self.assertEqual(exit_code, 1)
        self.assertEqual(error_output.getvalue(), "error: The media path is invalid.\n")
        self.assertNotIn("Traceback", error_output.getvalue())

    def test_debug_mode_retains_the_traceback(self) -> None:
        error_output = StringIO()

        exit_code = run_cli(
            self.fail_with_expected_error,
            debug=True,
            error_stream=error_output,
        )

        self.assertEqual(exit_code, 1)
        self.assertIn("Traceback (most recent call last)", error_output.getvalue())
        self.assertIn("UserInputError", error_output.getvalue())


class FakeInitProject:
    def __init__(self) -> None:
        self.requests: list[InitProjectRequest] = []

    def execute(self, request: InitProjectRequest) -> InitProjectResult:
        self.requests.append(request)
        return InitProjectResult(request.project_directory, request.project_id)


class InitCommandTest(unittest.TestCase):
    def test_calls_exactly_one_init_use_case_and_reports_success(self) -> None:
        fake = FakeInitProject()
        output = StringIO()

        exit_code = main(
            ["init", "/projects/demo", "--project-id", "demo"],
            services=CliServices(fake),
            output_stream=output,
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            fake.requests, [InitProjectRequest(Path("/projects/demo"), "demo")]
        )
        self.assertEqual(output.getvalue(), "Initialized project demo.\n")

    def test_missing_required_argument_exits_before_calling_service(self) -> None:
        fake = FakeInitProject()

        with self.assertRaises(SystemExit) as raised:
            main(["init", "/projects/demo"], services=CliServices(fake))

        self.assertEqual(raised.exception.code, 2)
        self.assertEqual(fake.requests, [])

    def test_real_use_case_creates_manifest(self) -> None:
        with TemporaryDirectory() as directory:
            project_directory = Path(directory) / "demo"

            exit_code = main(
                ["init", str(project_directory), "--project-id", "demo"],
                output_stream=StringIO(),
            )

            self.assertEqual(exit_code, 0)
            self.assertTrue((project_directory / "manifest.json").is_file())


class FakeTranscribe:
    def __init__(self) -> None:
        self.requests: list[TranscribeRequest] = []

    def execute(self, request: TranscribeRequest) -> TranscribeResult:
        self.requests.append(request)
        return TranscribeResult("transcript-1", "asset-1", 42)


class TranscribeCommandTest(unittest.TestCase):
    def test_calls_one_transcribe_use_case_and_reports_word_count(self) -> None:
        fake = FakeTranscribe()
        output = StringIO()

        exit_code = main(
            [
                "transcribe",
                "/projects/demo",
                "/media/input.mov",
                "--provider",
                "mlx",
                "--model",
                "large-v3-turbo",
            ],
            services=CliServices(FakeInitProject(), fake),
            output_stream=output,
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(fake.requests), 1)
        self.assertEqual(fake.requests[0].provider, "mlx")
        self.assertEqual(fake.requests[0].language, "zh")
        self.assertEqual(output.getvalue(), "Transcribed 42 words for asset asset-1.\n")

    def test_invalid_provider_exits_before_service_call(self) -> None:
        fake = FakeTranscribe()
        with self.assertRaises(SystemExit) as raised:
            main(
                [
                    "transcribe",
                    "/projects/demo",
                    "/media/input.mov",
                    "--provider",
                    "invalid",
                    "--model",
                    "small",
                ],
                services=CliServices(FakeInitProject(), fake),
            )
        self.assertEqual(raised.exception.code, 2)
        self.assertEqual(fake.requests, [])


class FakePlan:
    def __init__(self) -> None:
        self.requests: list[PlanRequest] = []

    def execute(self, request: PlanRequest) -> PlanResult:
        self.requests.append(request)
        return PlanResult("asset-1", 3, 1, Path("/project/plan.json"))


class PlanCommandTest(unittest.TestCase):
    def test_calls_one_plan_use_case_with_typed_options(self) -> None:
        fake = FakePlan()
        output = StringIO()

        exit_code = main(
            [
                "plan",
                "/projects/demo",
                "--asset-id",
                "asset-1",
                "--target-ms",
                "60000",
                "--intensity",
                "aggressive",
                "--planner",
                "deepseek",
            ],
            services=CliServices(FakeInitProject(), plan=fake),
            output_stream=output,
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(fake.requests), 1)
        self.assertEqual(fake.requests[0].intensity, EditIntensity.AGGRESSIVE)
        self.assertEqual(fake.requests[0].planner, "deepseek")
        self.assertIn("3 kept and 1 deleted", output.getvalue())

    def test_nonpositive_target_exits_before_plan_service(self) -> None:
        fake = FakePlan()
        with self.assertRaises(SystemExit) as raised:
            main(
                [
                    "plan",
                    "/projects/demo",
                    "--asset-id",
                    "asset-1",
                    "--target-ms",
                    "0",
                ],
                services=CliServices(FakeInitProject(), plan=fake),
            )
        self.assertEqual(raised.exception.code, 2)
        self.assertEqual(fake.requests, [])


class FakeRender:
    def __init__(self) -> None:
        self.requests: list[RenderRequest] = []

    def execute(self, request: RenderRequest) -> RenderResult:
        self.requests.append(request)
        return RenderResult(
            request.output_path, request.output_path.with_suffix(".srt"), 900
        )


class RenderCommandTest(unittest.TestCase):
    def test_calls_one_render_use_case_and_reports_output(self) -> None:
        fake = FakeRender()
        output = StringIO()

        exit_code = main(
            [
                "render",
                "/projects/demo",
                "--asset-id",
                "asset-1",
                "--output",
                "/exports/result.mp4",
                "--timeout",
                "30",
            ],
            services=CliServices(FakeInitProject(), render=fake),
            output_stream=output,
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(fake.requests), 1)
        self.assertEqual(fake.requests[0].timeout_seconds, 30)
        self.assertIn("Rendered 900 ms", output.getvalue())

    def test_invalid_timeout_exits_before_render_service(self) -> None:
        fake = FakeRender()
        with self.assertRaises(SystemExit) as raised:
            main(
                [
                    "render",
                    "/projects/demo",
                    "--asset-id",
                    "asset-1",
                    "--output",
                    "/exports/result.mp4",
                    "--timeout",
                    "0",
                ],
                services=CliServices(FakeInitProject(), render=fake),
            )
        self.assertEqual(raised.exception.code, 2)
        self.assertEqual(fake.requests, [])


if __name__ == "__main__":
    unittest.main()
