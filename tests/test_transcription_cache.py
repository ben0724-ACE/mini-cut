import unittest

from minicut.mlx_whisper import MlxWhisperConfig
from minicut.open_source_whisper import OpenSourceWhisperConfig
from minicut.transcription_cache import (
    TranscriptionCacheKey,
    cache_key_for_mlx,
    cache_key_for_open_source_whisper,
)


class TranscriptionCacheKeyTest(unittest.TestCase):
    def test_same_inputs_produce_equal_structured_keys(self) -> None:
        config = MlxWhisperConfig(
            model_name="small",
            language="zh",
            initial_prompt="产品演示",
        )

        first = cache_key_for_mlx("sha256:media-a", config)
        second = cache_key_for_mlx("sha256:media-a", config)

        self.assertEqual(first, second)
        self.assertEqual(
            first,
            TranscriptionCacheKey(
                media_fingerprint="sha256:media-a",
                provider="mlx-whisper",
                model="small",
                language="zh",
                initial_prompt="产品演示",
            ),
        )

    def test_each_result_affecting_input_changes_the_key(self) -> None:
        baseline = cache_key_for_mlx(
            "sha256:media-a",
            MlxWhisperConfig(
                model_name="small",
                language="zh",
                initial_prompt="产品演示",
            ),
        )
        variations = (
            cache_key_for_mlx(
                "sha256:media-b",
                MlxWhisperConfig(
                    model_name="small",
                    language="zh",
                    initial_prompt="产品演示",
                ),
            ),
            cache_key_for_open_source_whisper(
                "sha256:media-a",
                OpenSourceWhisperConfig(
                    model_name="small",
                    language="zh",
                    initial_prompt="产品演示",
                ),
            ),
            cache_key_for_mlx(
                "sha256:media-a",
                MlxWhisperConfig(
                    model_name="base",
                    language="zh",
                    initial_prompt="产品演示",
                ),
            ),
            cache_key_for_mlx(
                "sha256:media-a",
                MlxWhisperConfig(
                    model_name="small",
                    language="en",
                    initial_prompt="产品演示",
                ),
            ),
            cache_key_for_mlx(
                "sha256:media-a",
                MlxWhisperConfig(
                    model_name="small",
                    language="zh",
                    initial_prompt="访谈",
                ),
            ),
        )

        for variation in variations:
            with self.subTest(variation=variation):
                self.assertNotEqual(variation, baseline)

    def test_execution_device_does_not_change_open_source_key(self) -> None:
        automatic = cache_key_for_open_source_whisper(
            "sha256:media-a",
            OpenSourceWhisperConfig(model_name="small", device=None),
        )
        cpu = cache_key_for_open_source_whisper(
            "sha256:media-a",
            OpenSourceWhisperConfig(model_name="small", device="cpu"),
        )

        self.assertEqual(cpu, automatic)

    def test_blank_required_fields_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "media_fingerprint"):
            cache_key_for_mlx(" ", MlxWhisperConfig())
        with self.assertRaisesRegex(ValueError, "provider"):
            TranscriptionCacheKey("sha256:media-a", " ", "small", "zh", None)
        with self.assertRaisesRegex(ValueError, "model"):
            TranscriptionCacheKey("sha256:media-a", "mlx-whisper", " ", "zh", None)
        with self.assertRaisesRegex(ValueError, "language"):
            TranscriptionCacheKey("sha256:media-a", "mlx-whisper", "small", " ", None)


if __name__ == "__main__":
    unittest.main()
