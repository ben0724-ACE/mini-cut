import shutil
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from minicut.audio_loudness import (
    LoudnessProfile,
    build_loudness_analysis_command,
    build_loudness_normalization_command,
    parse_loudness_measurement,
)
from minicut.renderer import FfmpegRenderer


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is required")
class RealLoudnessNormalizationTest(unittest.TestCase):
    def test_two_pass_normalization_reaches_configured_tolerance(self) -> None:
        profile = LoudnessProfile(target_lufs=-16, tolerance_lu=1)
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "quiet.wav"
            output = root / "normalized.m4a"
            generated = subprocess.run(
                (
                    "ffmpeg",
                    "-v",
                    "error",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=440:sample_rate=48000:duration=3",
                    "-af",
                    "volume=0.02",
                    str(source),
                ),
                capture_output=True,
                check=False,
            )
            self.assertEqual(generated.returncode, 0, generated.stderr.decode())

            first_pass = subprocess.run(
                build_loudness_analysis_command(source, profile),
                capture_output=True,
                check=False,
                text=True,
            )
            self.assertEqual(first_pass.returncode, 0, first_pass.stderr)
            measurement = parse_loudness_measurement(first_pass.stderr)
            command = build_loudness_normalization_command(
                source, output, profile, measurement
            )
            FfmpegRenderer().render_to_path(command, output, timeout_seconds=30)

            verification = subprocess.run(
                build_loudness_analysis_command(output, profile),
                capture_output=True,
                check=False,
                text=True,
            )
            self.assertEqual(verification.returncode, 0, verification.stderr)
            normalized = parse_loudness_measurement(verification.stderr)

        self.assertLessEqual(
            abs(normalized.input_lufs - profile.target_lufs), profile.tolerance_lu
        )
        self.assertLessEqual(normalized.input_true_peak_dbfs, profile.true_peak_dbfs)


if __name__ == "__main__":
    unittest.main()
