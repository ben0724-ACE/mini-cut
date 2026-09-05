import os
import unittest
from itertools import pairwise
from pathlib import Path

from minicut.mlx_whisper import (
    MlxWhisperConfig,
    map_mlx_transcription,
    transcribe_with_mlx,
)

_MEDIA_ENVIRONMENT_VARIABLE = "MINICUT_MLX_INTEGRATION_MEDIA"
_MEDIA_PATH = os.environ.get(_MEDIA_ENVIRONMENT_VARIABLE)


@unittest.skipUnless(
    _MEDIA_PATH,
    f"set {_MEDIA_ENVIRONMENT_VARIABLE} to run real MLX inference",
)
class RealMlxWhisperTest(unittest.TestCase):
    def test_real_chinese_media_produces_monotonic_timestamped_words(self) -> None:
        if _MEDIA_PATH is None:
            self.fail("integration media path was not configured")

        source_path = Path(_MEDIA_PATH)
        config = MlxWhisperConfig(
            model_name="large-v3-turbo",
            language="zh",
        )

        raw_response = transcribe_with_mlx(source_path, config)
        transcript = map_mlx_transcription(
            raw_response,
            asset_id=f"integration:{source_path.name}",
            config=config,
        )

        self.assertTrue(source_path.is_file())
        self.assertGreater(len(transcript.words), 0)
        self.assertTrue(all(word.text for word in transcript.words))
        self.assertTrue(
            all(
                type(value) is int
                for word in transcript.words
                for value in (word.start_ms, word.end_ms)
            )
        )
        self.assertTrue(
            all(
                previous.start_ms <= current.start_ms
                for previous, current in pairwise(transcript.words)
            )
        )


if __name__ == "__main__":
    unittest.main()
