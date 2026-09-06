import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

from minicut.errors import ProcessingError
from minicut.mlx_whisper import MlxWhisperConfig
from minicut.open_source_whisper import OpenSourceWhisperConfig
from minicut.transcript import Transcript, TranscriptSource, Utterance, Word
from minicut.transcription_cache import (
    TranscriptCacheRepository,
    TranscriptionCacheKey,
    cache_key_for_mlx,
    cache_key_for_open_source_whisper,
)


def _transcript(text: str = "你好") -> Transcript:
    source = TranscriptSource(
        asset_id="asset-1",
        provider="mlx-whisper",
        model="small",
    )
    word = Word(
        word_id=f"word:{text}",
        text=text,
        start_ms=100,
        end_ms=500,
        probability=0.98,
    )
    return Transcript(
        transcript_id=f"transcript:{text}",
        source=source,
        language="zh",
        words=(word,),
        utterances=(
            Utterance(
                utterance_id=f"utterance:{text}",
                text=text,
                start_ms=100,
                end_ms=500,
                word_ids=(word.word_id,),
            ),
        ),
    )


class CountingProducer:
    def __init__(self, result: Transcript) -> None:
        self.result = result
        self.calls = 0

    def __call__(self) -> Transcript:
        self.calls += 1
        return self.result


class ObservingCacheReplacer:
    def __init__(self) -> None:
        self.source_data: dict[str, object] | None = None
        self.destination_data: dict[str, object] | None = None

    def __call__(self, source: Path, destination: Path) -> None:
        self.source_data = cast(
            dict[str, object], json.loads(source.read_text(encoding="utf-8"))
        )
        self.destination_data = cast(
            dict[str, object], json.loads(destination.read_text(encoding="utf-8"))
        )
        source.replace(destination)


class FailingCacheReplacer:
    def __init__(self) -> None:
        self.temporary_path: Path | None = None

    def __call__(self, source: Path, destination: Path) -> None:
        del destination
        self.temporary_path = source
        raise OSError("private simulated cache failure")


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
        self.assertEqual(
            TranscriptionCacheKey.from_dict(first.to_dict()),
            first,
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


class TranscriptCacheRepositoryTest(unittest.TestCase):
    def test_cache_hit_does_not_call_the_producer_twice(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            repository = TranscriptCacheRepository(
                Path(temporary_directory) / "transcript-cache.json"
            )
            key = cache_key_for_mlx(
                "sha256:media-a", MlxWhisperConfig(model_name="small")
            )
            producer = CountingProducer(_transcript())

            first = repository.get_or_create(key, producer)
            second = repository.get_or_create(key, producer)

        self.assertEqual(producer.calls, 1)
        self.assertEqual(first, producer.result)
        self.assertEqual(second, producer.result)

    def test_changed_key_is_a_miss_and_replaces_the_entry(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            repository = TranscriptCacheRepository(
                Path(temporary_directory) / "transcript-cache.json"
            )
            original_key = cache_key_for_mlx(
                "sha256:media-a", MlxWhisperConfig(model_name="small")
            )
            changed_key = cache_key_for_mlx(
                "sha256:media-a", MlxWhisperConfig(model_name="base")
            )
            repository.write(original_key, _transcript("旧结果"))
            producer = CountingProducer(_transcript("新结果"))

            result = repository.get_or_create(changed_key, producer)

            self.assertEqual(producer.calls, 1)
            self.assertEqual(result, producer.result)
            self.assertIsNone(repository.read(original_key))
            self.assertEqual(repository.read(changed_key), producer.result)

    def test_write_publishes_one_complete_entry_with_atomic_replace(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "transcript-cache.json"
            original_key = cache_key_for_mlx(
                "sha256:media-a", MlxWhisperConfig(model_name="small")
            )
            changed_key = cache_key_for_mlx(
                "sha256:media-a", MlxWhisperConfig(model_name="base")
            )
            TranscriptCacheRepository(cache_path).write(
                original_key, _transcript("旧结果")
            )
            replacer = ObservingCacheReplacer()
            repository = TranscriptCacheRepository(
                cache_path,
                replace_file=replacer,
            )

            repository.write(changed_key, _transcript("新结果"))

            assert replacer.destination_data is not None
            assert replacer.source_data is not None
            self.assertEqual(replacer.destination_data["key"], original_key.to_dict())
            self.assertEqual(replacer.source_data["key"], changed_key.to_dict())
            self.assertEqual(repository.read(changed_key), _transcript("新结果"))

    def test_interrupted_write_preserves_the_previous_entry(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            cache_path = Path(temporary_directory) / "transcript-cache.json"
            original_key = cache_key_for_mlx(
                "sha256:media-a", MlxWhisperConfig(model_name="small")
            )
            original = _transcript("旧结果")
            TranscriptCacheRepository(cache_path).write(original_key, original)
            replacer = FailingCacheReplacer()
            repository = TranscriptCacheRepository(
                cache_path,
                replace_file=replacer,
            )

            with self.assertRaisesRegex(
                ProcessingError,
                "cache could not be written",
            ) as raised:
                repository.write(original_key, _transcript("新结果"))

            self.assertIsInstance(raised.exception.__cause__, OSError)
            self.assertNotIn("private simulated", str(raised.exception))
            self.assertEqual(repository.read(original_key), original)
            self.assertIsNotNone(replacer.temporary_path)
            assert replacer.temporary_path is not None
            self.assertFalse(replacer.temporary_path.exists())


if __name__ == "__main__":
    unittest.main()
