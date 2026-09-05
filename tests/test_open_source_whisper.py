import unittest
from unittest.mock import patch

from minicut.errors import ProcessingError, UserInputError
from minicut.open_source_whisper import (
    OpenSourceWhisperConfig,
    transcribe_with_open_source_whisper,
)


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


if __name__ == "__main__":
    unittest.main()
