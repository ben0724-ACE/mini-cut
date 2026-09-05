import unittest

from minicut.errors import UserInputError
from minicut.mlx_whisper import (
    MlxWhisperConfig,
    resolve_mlx_model_repository,
    transcribe_with_mlx,
)


class RecordingMlxTranscribe:
    def __init__(self) -> None:
        self.audio: str | None = None
        self.path_or_hf_repo: str | None = None
        self.language: str | None = None
        self.initial_prompt: str | None = None
        self.word_timestamps: bool | None = None
        self.verbose: bool | None = None
        self.result: dict[str, object] = {"text": "你好", "segments": []}

    def __call__(
        self,
        audio: str,
        *,
        path_or_hf_repo: str,
        language: str,
        initial_prompt: str | None,
        word_timestamps: bool,
        verbose: bool,
    ) -> dict[str, object]:
        self.audio = audio
        self.path_or_hf_repo = path_or_hf_repo
        self.language = language
        self.initial_prompt = initial_prompt
        self.word_timestamps = word_timestamps
        self.verbose = verbose
        return self.result


class MlxWhisperConfigTest(unittest.TestCase):
    def test_defaults_target_the_verified_turbo_repository_for_chinese(self) -> None:
        config = MlxWhisperConfig()

        self.assertEqual(config.model_name, "large-v3-turbo")
        self.assertEqual(
            config.model_repository,
            "mlx-community/whisper-large-v3-turbo",
        )
        self.assertEqual(config.language, "zh")
        self.assertIsNone(config.initial_prompt)

    def test_supported_model_aliases_resolve_to_mlx_repositories(self) -> None:
        expected_repositories = {
            "small": "mlx-community/whisper-small-mlx",
            "large-v3": "mlx-community/whisper-large-v3-mlx",
        }

        for model_name, expected_repository in expected_repositories.items():
            with self.subTest(model_name=model_name):
                self.assertEqual(
                    resolve_mlx_model_repository(model_name),
                    expected_repository,
                )

    def test_unsupported_model_is_rejected_with_supported_aliases(self) -> None:
        with self.assertRaisesRegex(
            UserInputError,
            "Unsupported MLX Whisper model.*large-v3-turbo",
        ):
            MlxWhisperConfig(model_name="unknown-model")

    def test_blank_language_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "language"):
            MlxWhisperConfig(language="  ")


class MlxWhisperInvocationTest(unittest.TestCase):
    def test_invocation_enables_word_timestamps_and_uses_config(self) -> None:
        backend = RecordingMlxTranscribe()
        config = MlxWhisperConfig(
            model_name="large-v3-turbo",
            language="zh",
            initial_prompt="这是一个产品演示",
        )

        result = transcribe_with_mlx(
            "/media/source.mov",
            config,
            transcribe=backend,
        )

        self.assertIs(result, backend.result)
        self.assertEqual(backend.audio, "/media/source.mov")
        self.assertEqual(backend.path_or_hf_repo, config.model_repository)
        self.assertEqual(backend.language, "zh")
        self.assertEqual(backend.initial_prompt, "这是一个产品演示")
        self.assertIs(backend.word_timestamps, True)
        self.assertIs(backend.verbose, False)

    def test_invocation_forwards_an_absent_prompt_as_none(self) -> None:
        backend = RecordingMlxTranscribe()

        transcribe_with_mlx(
            "/media/source.mov",
            MlxWhisperConfig(),
            transcribe=backend,
        )

        self.assertIsNone(backend.initial_prompt)


if __name__ == "__main__":
    unittest.main()
