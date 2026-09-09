import subprocess
import unittest

from minicut.audio_quality import (
    AudioContinuityMetrics,
    AudioQualityCode,
    assess_audio_continuity,
    build_audio_analysis_command,
    measure_audio_continuity,
    parse_audio_analysis,
)
from minicut.errors import ProcessingError
from minicut.probe import ProcessResult
from minicut.timeline_validation import ValidationSeverity


class AudioAnalysisTest(unittest.TestCase):
    def test_builds_safe_command_and_parses_silence_and_peak(self) -> None:
        command = build_audio_analysis_command("/media/采访 take.wav")
        silence_ms, peak_dbfs = parse_audio_analysis(
            "silence_duration: 0.500\n"
            "silence_duration: 1.250\n"
            "Peak level dB: -6.20\n"
            "Peak level dB: -3.00\n"
        )

        self.assertEqual(
            command[command.index("-i") + 1],
            "file:///media/%E9%87%87%E8%AE%BF%20take.wav",
        )
        self.assertIn("silencedetect", command[command.index("-af") + 1])
        self.assertEqual(silence_ms, 1_750)
        self.assertEqual(peak_dbfs, -3.0)

    def test_measurement_executes_runner_and_maps_failures(self) -> None:
        calls: list[tuple[tuple[str, ...], float]] = []

        def successful_runner(
            command: tuple[str, ...], timeout_seconds: float
        ) -> ProcessResult:
            calls.append((command, timeout_seconds))
            return ProcessResult(0, "", "Peak level dB: -12.0")

        metrics = measure_audio_continuity(
            "/media/result.mp4",
            audio_duration_ms=1_000,
            video_duration_ms=1_020,
            runner=successful_runner,
            timeout_seconds=4,
        )
        self.assertEqual(metrics.peak_dbfs, -12.0)
        self.assertEqual(calls[0][1], 4)

        def failing_runner(
            command: tuple[str, ...], timeout_seconds: float
        ) -> ProcessResult:
            del command, timeout_seconds
            return ProcessResult(1, "", "private")

        def timeout_runner(
            command: tuple[str, ...], timeout_seconds: float
        ) -> ProcessResult:
            raise subprocess.TimeoutExpired(command, timeout_seconds)

        failures = ((failing_runner, "could not"), (timeout_runner, "timed out"))
        for runner, message in failures:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ProcessingError, message):
                    measure_audio_continuity(
                        "/media/result.mp4",
                        audio_duration_ms=1_000,
                        runner=runner,
                    )


class AudioContinuityAssessmentTest(unittest.TestCase):
    def test_reports_silence_clipping_and_blocking_av_mismatch(self) -> None:
        report = assess_audio_continuity(
            AudioContinuityMetrics(
                True,
                audio_duration_ms=1_000,
                video_duration_ms=1_100,
                silence_duration_ms=950,
                peak_dbfs=-0.05,
            ),
            frame_rate="30",
        )

        self.assertEqual(report.max_av_delta_ms, 40)
        self.assertEqual(
            tuple(issue.code for issue in report.issues),
            (
                AudioQualityCode.EXCESSIVE_SILENCE,
                AudioQualityCode.CLIPPING_RISK,
                AudioQualityCode.AV_DURATION_MISMATCH,
            ),
        )
        self.assertEqual(report.issues[-1].severity, ValidationSeverity.ERROR)
        self.assertFalse(report.can_publish)

    def test_accepts_delta_at_larger_of_one_frame_or_forty_ms(self) -> None:
        cases = (("30", 40), ("20", 50), ("30000/1001", 40))

        for frame_rate, accepted_delta_ms in cases:
            with self.subTest(frame_rate=frame_rate):
                report = assess_audio_continuity(
                    AudioContinuityMetrics(
                        True,
                        audio_duration_ms=1_000,
                        video_duration_ms=1_000 + accepted_delta_ms,
                        peak_dbfs=-6,
                    ),
                    frame_rate=frame_rate,
                )
                self.assertTrue(report.can_publish)
                self.assertEqual(report.issues, ())

    def test_no_audio_is_valid_for_silent_video_policy(self) -> None:
        report = assess_audio_continuity(
            AudioContinuityMetrics(False, video_duration_ms=1_000),
            frame_rate="30",
        )

        self.assertTrue(report.can_publish)
        self.assertEqual(report.issues, ())


if __name__ == "__main__":
    unittest.main()
