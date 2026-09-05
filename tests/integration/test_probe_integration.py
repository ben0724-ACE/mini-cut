import shutil
import unittest
import wave
from pathlib import Path
from tempfile import TemporaryDirectory

from minicut.media import StreamType
from minicut.probe import probe_media


@unittest.skipUnless(shutil.which("ffprobe"), "ffprobe is required")
class RealFfprobeTest(unittest.TestCase):
    def test_generated_wav_duration_is_within_twenty_milliseconds(self) -> None:
        sample_rate = 8_000
        frame_count = 800
        expected_duration_ms = 100

        with TemporaryDirectory() as temporary_directory:
            source_path = Path(temporary_directory) / "short.wav"
            with wave.open(str(source_path), "wb") as audio_file:
                audio_file.setnchannels(1)
                audio_file.setsampwidth(2)
                audio_file.setframerate(sample_rate)
                audio_file.writeframes(b"\x00\x00" * frame_count)

            result = probe_media(source_path)

        duration_error_ms = abs(result.duration_ms - expected_duration_ms)
        self.assertLessEqual(duration_error_ms, 20)
        self.assertEqual(
            tuple(stream.stream_type for stream in result.streams),
            (StreamType.AUDIO,),
        )


if __name__ == "__main__":
    unittest.main()
