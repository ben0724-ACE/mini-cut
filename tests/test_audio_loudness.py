import unittest

from minicut.audio_loudness import (
    LoudnessMeasurement,
    LoudnessProfile,
    build_loudness_analysis_command,
    build_loudness_normalization_command,
    measure_loudness,
    parse_loudness_measurement,
)
from minicut.probe import ProcessResult


class LoudnessCommandTest(unittest.TestCase):
    def test_builds_two_pass_analysis_and_normalization_commands(self) -> None:
        profile = LoudnessProfile(target_lufs=-16, true_peak_dbfs=-1.5)
        analysis = build_loudness_analysis_command("/media/input file.mp4", profile)
        measurement = LoudnessMeasurement(-23.1, -8.2, 4.3, -33.5, 0.2)
        normalization = build_loudness_normalization_command(
            "/media/input file.mp4",
            "/output/result.mp4",
            profile,
            measurement,
        )

        self.assertEqual(
            analysis[analysis.index("-i") + 1], "file:///media/input%20file.mp4"
        )
        self.assertIn("print_format=json", analysis[analysis.index("-af") + 1])
        loudnorm = normalization[normalization.index("-af") + 1]
        self.assertIn("I=-16.0", loudnorm)
        self.assertIn("measured_I=-23.1", loudnorm)
        self.assertIn("measured_TP=-8.2", loudnorm)
        self.assertIn("linear=true", loudnorm)
        self.assertEqual(normalization[-1], "file:///output/result.mp4")

    def test_parses_ffmpeg_json_measurement(self) -> None:
        measurement = parse_loudness_measurement(
            "[Parsed_loudnorm] {\n"
            '  "input_i" : "-21.35",\n'
            '  "input_tp" : "-4.10",\n'
            '  "input_lra" : "3.20",\n'
            '  "input_thresh" : "-31.70",\n'
            '  "target_offset" : "0.15"\n'
            "}\n"
        )

        self.assertEqual(
            measurement,
            LoudnessMeasurement(-21.35, -4.1, 3.2, -31.7, 0.15),
        )

    def test_rejects_invalid_profile_or_measurement_output(self) -> None:
        for profile in (
            lambda: LoudnessProfile(target_lufs=-80),
            lambda: LoudnessProfile(true_peak_dbfs=1),
            lambda: LoudnessProfile(tolerance_lu=0),
        ):
            with self.subTest(profile=profile):
                with self.assertRaises(ValueError):
                    profile()
        with self.assertRaisesRegex(ValueError, "measurement"):
            parse_loudness_measurement("no loudness JSON")

    def test_measurement_executes_injected_runner(self) -> None:
        calls: list[tuple[tuple[str, ...], float]] = []

        def runner(command: tuple[str, ...], timeout_seconds: float) -> ProcessResult:
            calls.append((command, timeout_seconds))
            return ProcessResult(
                0,
                "",
                '{"input_i":"-20","input_tp":"-5","input_lra":"2",'
                '"input_thresh":"-30","target_offset":"0"}',
            )

        measured = measure_loudness(
            "/media/input.mp4", LoudnessProfile(), runner=runner, timeout_seconds=12
        )

        self.assertEqual(measured.input_lufs, -20)
        self.assertEqual(calls[0][1], 12)


if __name__ == "__main__":
    unittest.main()
