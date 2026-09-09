import math
import shutil
import struct
import unittest
import wave
from pathlib import Path
from tempfile import TemporaryDirectory

from minicut.audio_quality import assess_audio_continuity, measure_audio_continuity


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is required")
class RealAudioQualityTest(unittest.TestCase):
    def test_fixed_faded_tone_has_no_clipping_risk(self) -> None:
        sample_rate = 48_000
        duration_ms = 600
        frame_count = sample_rate * duration_ms // 1_000
        frames = bytearray()
        for index in range(frame_count):
            edge_gain = min(index / 480, (frame_count - index - 1) / 480, 1.0)
            sample = round(
                math.sin(2 * math.pi * 440 * index / sample_rate)
                * 0.25
                * edge_gain
                * 32_767
            )
            frames.extend(struct.pack("<h", sample))

        with TemporaryDirectory() as directory:
            source_path = Path(directory) / "fixed-faded-tone.wav"
            with wave.open(str(source_path), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(sample_rate)
                output.writeframes(frames)

            metrics = measure_audio_continuity(
                source_path,
                audio_duration_ms=duration_ms,
            )
            report = assess_audio_continuity(metrics, frame_rate="30")

        self.assertTrue(report.can_publish)
        self.assertEqual(report.issues, ())
        self.assertIsNotNone(metrics.peak_dbfs)
        assert metrics.peak_dbfs is not None
        self.assertLess(metrics.peak_dbfs, -0.1)


if __name__ == "__main__":
    unittest.main()
