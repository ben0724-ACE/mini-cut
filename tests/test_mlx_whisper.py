import copy
import unittest

from minicut.errors import UserInputError
from minicut.mlx_whisper import (
    MlxWhisperConfig,
    map_mlx_transcription,
    resolve_mlx_model_repository,
    transcribe_with_mlx,
)
from minicut.transcript import Transcript


def _raw_mlx_response() -> dict[str, object]:
    return {
        "text": " 你好 世界",
        "language": "zh",
        "segments": [
            {
                "id": 0,
                "start": 0.0,
                "end": 1.0,
                "text": " 你好",
                "words": [
                    {
                        "word": " 你",
                        "start": 0.0,
                        "end": 0.4,
                        "probability": 0.98,
                    },
                    {
                        "word": "好",
                        "start": 0.4,
                        "end": 0.9,
                        "probability": 0.96,
                    },
                ],
            },
            {
                "id": 1,
                "start": 1.1,
                "end": 2.0,
                "text": " 世界",
                "words": [
                    {
                        "word": " 世",
                        "start": 1.1,
                        "end": 1.5,
                        "probability": 0.94,
                    },
                    {
                        "word": "界",
                        "start": 1.5,
                        "end": 2.0,
                        "probability": 0.93,
                    },
                ],
            },
        ],
    }


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


class MlxWhisperMappingTest(unittest.TestCase):
    def test_fixed_chinese_response_maps_to_transcript_v1(self) -> None:
        transcript = map_mlx_transcription(
            _raw_mlx_response(),
            asset_id="asset-1",
            config=MlxWhisperConfig(),
        )

        self.assertIsInstance(transcript, Transcript)
        self.assertEqual(transcript.source.asset_id, "asset-1")
        self.assertEqual(transcript.source.provider, "mlx-whisper")
        self.assertEqual(transcript.source.model, "large-v3-turbo")
        self.assertEqual(transcript.language, "zh")
        self.assertEqual(
            tuple(word.text for word in transcript.words),
            ("你", "好", "世", "界"),
        )
        self.assertEqual(
            tuple((word.start_ms, word.end_ms) for word in transcript.words),
            ((0, 400), (400, 900), (1_100, 1_500), (1_500, 2_000)),
        )
        self.assertEqual(
            tuple(word.probability for word in transcript.words),
            (0.98, 0.96, 0.94, 0.93),
        )
        self.assertEqual(
            tuple(utterance.text for utterance in transcript.utterances),
            ("你好", "世界"),
        )
        self.assertEqual(
            tuple(
                (utterance.start_ms, utterance.end_ms)
                for utterance in transcript.utterances
            ),
            ((0, 1_000), (1_100, 2_000)),
        )
        self.assertEqual(
            transcript.utterances[0].word_ids,
            tuple(word.word_id for word in transcript.words[:2]),
        )
        self.assertEqual(
            transcript.utterances[1].word_ids,
            tuple(word.word_id for word in transcript.words[2:]),
        )
        self.assertEqual(len({word.word_id for word in transcript.words}), 4)
        self.assertTrue(all(type(word.start_ms) is int for word in transcript.words))

    def test_mapping_is_deterministic_and_does_not_mutate_raw_response(self) -> None:
        raw_response = _raw_mlx_response()
        original_response = copy.deepcopy(raw_response)
        config = MlxWhisperConfig()

        first = map_mlx_transcription(
            raw_response,
            asset_id="asset-1",
            config=config,
        )
        second = map_mlx_transcription(
            raw_response,
            asset_id="asset-1",
            config=config,
        )

        self.assertEqual(second, first)
        self.assertEqual(raw_response, original_response)


if __name__ == "__main__":
    unittest.main()
