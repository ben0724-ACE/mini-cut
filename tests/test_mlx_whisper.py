import unittest

from minicut.errors import UserInputError
from minicut.mlx_whisper import MlxWhisperConfig, resolve_mlx_model_repository


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


if __name__ == "__main__":
    unittest.main()
