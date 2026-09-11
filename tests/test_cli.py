import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from minicut.application import (
    EditProgressEvent,
    EditRequest,
    EditResult,
    InitProjectRequest,
    InitProjectResult,
    InspectedAsset,
    InspectRequest,
    InspectResult,
    ModifyPlanRequest,
    ModifyPlanResult,
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
from minicut.render_command import SubtitleMode


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
        self.assertEqual(fake.requests[0].subtitle_mode, SubtitleMode.SOFT)
        self.assertIn("Rendered 900 ms", output.getvalue())

    def test_passes_optional_burned_subtitle_mode(self) -> None:
        fake = FakeRender()

        exit_code = main(
            [
                "render",
                "/projects/demo",
                "--asset-id",
                "asset-1",
                "--output",
                "/exports/result.mp4",
                "--subtitle-mode",
                "burned",
                "--audio-crossfade-ms",
                "25",
                "--denoiser",
                "afftdn",
                "--normalize-loudness",
            ],
            services=CliServices(FakeInitProject(), render=fake),
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(fake.requests[0].subtitle_mode, SubtitleMode.BURNED)
        self.assertEqual(fake.requests[0].audio_crossfade_ms, 25)
        self.assertEqual(fake.requests[0].denoiser_id, "afftdn")
        assert fake.requests[0].loudness_profile is not None
        self.assertEqual(fake.requests[0].loudness_profile.target_lufs, -16)

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


class FakeInspect:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.requests: list[InspectRequest] = []

    def execute(self, request: InspectRequest) -> InspectResult:
        self.requests.append(request)
        if self.fail:
            raise UserInputError("Project asset does not exist")
        return InspectResult(
            "demo",
            ("asset-1",),
            InspectedAsset("asset-1", "/media/input.mov", 1_000, True, 5, True, 3, 1),
        )


class InspectCommandTest(unittest.TestCase):
    def test_calls_one_inspect_use_case_and_prints_json(self) -> None:
        fake = FakeInspect()
        output = StringIO()

        exit_code = main(
            ["inspect", "/projects/demo", "--asset-id", "asset-1"],
            services=CliServices(FakeInitProject(), inspect=fake),
            output_stream=output,
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(fake.requests), 1)
        self.assertEqual(fake.requests[0].asset_id, "asset-1")
        self.assertIn('"transcript_word_count": 5', output.getvalue())

    def test_domain_error_returns_one_after_one_service_call(self) -> None:
        fake = FakeInspect(fail=True)
        errors = StringIO()

        exit_code = main(
            ["inspect", "/projects/demo", "--asset-id", "missing"],
            services=CliServices(FakeInitProject(), inspect=fake),
            error_stream=errors,
        )

        self.assertEqual(exit_code, 1)
        self.assertEqual(len(fake.requests), 1)
        self.assertEqual(errors.getvalue(), "error: Project asset does not exist\n")


class FakeEdit:
    def __init__(self) -> None:
        self.requests: list[EditRequest] = []

    def execute(self, request: EditRequest) -> EditResult:
        self.requests.append(request)
        request.on_progress(EditProgressEvent("transcribe", "running"))
        request.on_progress(EditProgressEvent("transcribe", "succeeded", True))
        request.on_progress(EditProgressEvent("render", "succeeded", False, 900))
        return EditResult(
            "asset-1",
            request.output_path,
            request.output_path.with_suffix(".srt"),
            900,
            (),
        )


class EditCommandTest(unittest.TestCase):
    def test_calls_one_edit_use_case(self) -> None:
        fake = FakeEdit()
        output = StringIO()

        exit_code = main(
            [
                "edit",
                "/projects/demo",
                "/media/input.mov",
                "--provider",
                "mlx",
                "--model",
                "large-v3-turbo",
                "--target-ms",
                "60000",
                "--output",
                "/exports/result.mp4",
            ],
            services=CliServices(FakeInitProject(), edit=fake),
            output_stream=output,
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(fake.requests), 1)
        self.assertEqual(fake.requests[0].target_duration_ms, 60_000)
        self.assertIn("Edited asset asset-1", output.getvalue())
        self.assertIn("[transcribe] running", output.getvalue())
        self.assertIn("[transcribe] reused", output.getvalue())
        self.assertIn("[render] succeeded; estimated output 900 ms", output.getvalue())


class FakeModifyPlan:
    def __init__(self) -> None:
        self.requests: list[ModifyPlanRequest] = []

    def execute(self, request: ModifyPlanRequest) -> ModifyPlanResult:
        self.requests.append(request)
        return ModifyPlanResult(
            request.asset_id,
            2,
            1,
            Path("plan.json"),
            Path("plan.txt"),
            2,
            (Path("0001.json"), Path("0002.json")),
            request.output_path,
            900,
        )


class ModifyPlanCommandTest(unittest.TestCase):
    def test_calls_one_modify_use_case_with_segment_actions(self) -> None:
        fake = FakeModifyPlan()
        output = StringIO()

        exit_code = main(
            [
                "plan-edit",
                "/projects/demo",
                "--asset-id",
                "asset-1",
                "--restore",
                "segment-2",
                "--delete",
                "segment-1",
                "--output",
                "/exports/revised.mp4",
            ],
            services=CliServices(FakeInitProject(), modify_plan=fake),
            output_stream=output,
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(fake.requests), 1)
        self.assertEqual(fake.requests[0].restore_segment_ids, ("segment-2",))
        self.assertEqual(fake.requests[0].delete_segment_ids, ("segment-1",))
        self.assertEqual(fake.requests[0].output_path, Path("/exports/revised.mp4"))
        self.assertIn("2 kept and 1 deleted", output.getvalue())
        self.assertIn("Rendered revision 2", output.getvalue())


if __name__ == "__main__":
    unittest.main()
