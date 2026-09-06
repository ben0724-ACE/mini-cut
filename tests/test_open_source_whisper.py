import unittest
from copy import deepcopy
from typing import cast
from unittest.mock import patch

from minicut.errors import ProcessingError, UserInputError
from minicut.open_source_whisper import (
    OpenSourceWhisperConfig,
    offset_vad_chunk_timestamps,
    transcribe_with_open_source_whisper,
)


def _raw_chunk_response(text: str) -> dict[str, object]:
    return {
        "text": text,
        "language": "zh",
        "segments": [
            {
                "start": 0.1,
                "end": 0.9,
                "text": text,
                "words": [
                    {
                        "word": text,
                        "start": 0.2,
                        "end": 0.8,
                        "probability": 0.95,
                    }
                ],
            }
        ],
    }


class RecordingWhisperModel:
    def __init__(self) -> None:
        self.audio: str | None = None
        self.task: str | None = None
        self.language: str | None = None
        self.initial_prompt: str | None = None
        self.word_timestamps: bool | None = None
        self.verbose: bool | None = None
        self.result: dict[str, object] = {"text": "你好", "segments": []}

    def transcribe(
        self,
        audio: str,
        *,
        task: str,
        language: str,
        initial_prompt: str | None,
        word_timestamps: bool,
        verbose: bool,
    ) -> dict[str, object]:
        self.audio = audio
        self.task = task
        self.language = language
        self.initial_prompt = initial_prompt
        self.word_timestamps = word_timestamps
        self.verbose = verbose
        return self.result


class RecordingWhisperLoader:
    def __init__(self, model: RecordingWhisperModel) -> None:
        self.model = model
        self.model_name: str | None = None
        self.device: str | None = None

    def __call__(
        self,
        model_name: str,
        *,
        device: str | None,
    ) -> RecordingWhisperModel:
        self.model_name = model_name
        self.device = device
        return self.model


class FailingWhisperLoader:
    def __call__(
        self,
        model_name: str,
        *,
        device: str | None,
    ) -> RecordingWhisperModel:
        del model_name, device
        raise RuntimeError("failed in /Users/private/model-cache")


class FailingWhisperModel(RecordingWhisperModel):
    def transcribe(
        self,
        audio: str,
        *,
        task: str,
        language: str,
        initial_prompt: str | None,
        word_timestamps: bool,
        verbose: bool,
    ) -> dict[str, object]:
        del audio, task, language, initial_prompt, word_timestamps, verbose
        raise RuntimeError("failed while reading /Users/private/audio.mov")


class OpenSourceWhisperConfigTest(unittest.TestCase):
    def test_defaults_match_autocut_local_whisper_settings(self) -> None:
        config = OpenSourceWhisperConfig()

        self.assertEqual(config.model_name, "small")
        self.assertEqual(config.language, "zh")
        self.assertIsNone(config.device)
        self.assertIsNone(config.initial_prompt)

    def test_unsupported_model_is_rejected(self) -> None:
        with self.assertRaisesRegex(UserInputError, "Unsupported Whisper model"):
            OpenSourceWhisperConfig(model_name="unknown-model")

    def test_blank_language_and_device_are_rejected(self) -> None:
        invalid_settings = ({"language": " "}, {"device": " "})

        for settings in invalid_settings:
            with self.subTest(settings=settings):
                with self.assertRaisesRegex(ValueError, "must not be blank"):
                    OpenSourceWhisperConfig(**settings)


class OpenSourceWhisperInvocationTest(unittest.TestCase):
    def test_model_is_loaded_and_word_timestamps_are_enabled(self) -> None:
        model = RecordingWhisperModel()
        loader = RecordingWhisperLoader(model)
        config = OpenSourceWhisperConfig(
            model_name="base",
            language="zh",
            device="cpu",
            initial_prompt="这是一个产品演示",
        )

        result = transcribe_with_open_source_whisper(
            "/media/source.mov",
            config,
            load_model=loader,
        )

        self.assertIs(result, model.result)
        self.assertEqual(loader.model_name, "base")
        self.assertEqual(loader.device, "cpu")
        self.assertEqual(model.audio, "/media/source.mov")
        self.assertEqual(model.task, "transcribe")
        self.assertEqual(model.language, "zh")
        self.assertEqual(model.initial_prompt, "这是一个产品演示")
        self.assertIs(model.word_timestamps, True)
        self.assertIs(model.verbose, False)

    def test_missing_backend_becomes_safe_processing_error(self) -> None:
        import_failure = ModuleNotFoundError("whisper missing in /Users/private")

        with patch(
            "minicut.open_source_whisper.import_module",
            side_effect=import_failure,
        ):
            with self.assertRaisesRegex(
                ProcessingError,
                "open-source Whisper backend is not available",
            ) as raised:
                transcribe_with_open_source_whisper(
                    "/media/source.mov",
                    OpenSourceWhisperConfig(),
                )

        self.assertIs(raised.exception.__cause__, import_failure)
        self.assertNotIn("/Users/private", str(raised.exception))

    def test_model_loading_failure_becomes_safe_processing_error(self) -> None:
        with self.assertRaisesRegex(
            ProcessingError,
            "open-source Whisper model loading failed",
        ) as raised:
            transcribe_with_open_source_whisper(
                "/media/source.mov",
                OpenSourceWhisperConfig(),
                load_model=FailingWhisperLoader(),
            )

        self.assertIsInstance(raised.exception.__cause__, RuntimeError)
        self.assertNotIn("/Users/private", str(raised.exception))

    def test_inference_failure_becomes_safe_processing_error(self) -> None:
        loader = RecordingWhisperLoader(FailingWhisperModel())

        with self.assertRaisesRegex(
            ProcessingError,
            "open-source Whisper transcription failed",
        ) as raised:
            transcribe_with_open_source_whisper(
                "/media/source.mov",
                OpenSourceWhisperConfig(),
                load_model=loader,
            )

        self.assertIsInstance(raised.exception.__cause__, RuntimeError)
        self.assertNotIn("/Users/private", str(raised.exception))


class OpenSourceWhisperVadOffsetTest(unittest.TestCase):
    def test_multiple_chunks_get_absolute_segment_and_word_times(self) -> None:
        first_raw = _raw_chunk_response("第一段")
        second_raw = _raw_chunk_response("第二段")
        first_original = deepcopy(first_raw)
        second_original = deepcopy(second_raw)

        first = offset_vad_chunk_timestamps(first_raw, origin_ms=1_000)
        second = offset_vad_chunk_timestamps(second_raw, origin_ms=5_000)

        first_segment = cast(list[dict[str, object]], first["segments"])[0]
        second_segment = cast(list[dict[str, object]], second["segments"])[0]
        first_word = cast(list[dict[str, object]], first_segment["words"])[0]
        second_word = cast(list[dict[str, object]], second_segment["words"])[0]
        self.assertEqual((first_segment["start"], first_segment["end"]), (1.1, 1.9))
        self.assertEqual((first_word["start"], first_word["end"]), (1.2, 1.8))
        self.assertEqual((second_segment["start"], second_segment["end"]), (5.1, 5.9))
        self.assertEqual((second_word["start"], second_word["end"]), (5.2, 5.8))
        self.assertLess(
            cast(float, first_word["end"]), cast(float, second_word["start"])
        )
        self.assertEqual(first_raw, first_original)
        self.assertEqual(second_raw, second_original)

    def test_negative_origin_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "origin_ms"):
            offset_vad_chunk_timestamps(_raw_chunk_response("测试"), origin_ms=-1)

    def test_missing_word_timestamp_becomes_safe_processing_error(self) -> None:
        response = _raw_chunk_response("测试")
        segment = cast(list[dict[str, object]], response["segments"])[0]
        word = cast(list[dict[str, object]], segment["words"])[0]
        word.pop("start")

        with self.assertRaisesRegex(
            ProcessingError,
            "invalid VAD chunk timestamps",
        ) as raised:
            offset_vad_chunk_timestamps(response, origin_ms=1_000)

        self.assertIsInstance(raised.exception.__cause__, KeyError)


if __name__ == "__main__":
    unittest.main()
