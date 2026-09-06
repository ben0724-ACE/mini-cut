import unittest
from copy import deepcopy
from itertools import pairwise
from typing import Literal, cast

from minicut.errors import ProcessingError
from minicut.mlx_whisper import MlxWhisperConfig, map_mlx_transcription
from minicut.open_source_whisper import (
    OpenSourceWhisperConfig,
    map_open_source_whisper_transcription,
)
from minicut.transcript import Transcript

ProviderName = Literal["mlx", "open-source"]


def _raw_whisper_response() -> dict[str, object]:
    return {
        "text": " 你好 世界",
        "language": "zh",
        "segments": [
            {
                "start": 1.0,
                "end": 2.0,
                "text": " 你好 世界",
                "words": [
                    {
                        "word": " 你好",
                        "start": 1.0,
                        "end": 1.4,
                        "probability": 0.98,
                    },
                    {
                        "word": " 世界",
                        "start": 1.5,
                        "end": 2.0,
                        "probability": 0.96,
                    },
                ],
            }
        ],
    }


def _map_provider(
    provider: ProviderName,
    response: dict[str, object],
) -> Transcript:
    if provider == "mlx":
        return map_mlx_transcription(
            response,
            asset_id="asset-1",
            config=MlxWhisperConfig(model_name="small"),
        )
    return map_open_source_whisper_transcription(
        response,
        asset_id="asset-1",
        config=OpenSourceWhisperConfig(model_name="small"),
    )


def _content_projection(transcript: Transcript) -> tuple[object, ...]:
    word_ordinals = {
        word.word_id: ordinal for ordinal, word in enumerate(transcript.words)
    }
    return (
        transcript.schema_version,
        transcript.language,
        tuple(
            (word.text, word.start_ms, word.end_ms, word.probability)
            for word in transcript.words
        ),
        tuple(
            (
                utterance.text,
                utterance.start_ms,
                utterance.end_ms,
                tuple(word_ordinals[word_id] for word_id in utterance.word_ids),
            )
            for utterance in transcript.utterances
        ),
    )


class WhisperProviderContractTest(unittest.TestCase):
    def test_both_providers_emit_the_same_normalized_contract(self) -> None:
        transcripts: list[Transcript] = []

        for provider in ("mlx", "open-source"):
            with self.subTest(provider=provider):
                response = _raw_whisper_response()
                original = deepcopy(response)
                transcript = _map_provider(provider, response)
                transcripts.append(transcript)

                self.assertEqual(transcript.source.asset_id, "asset-1")
                self.assertEqual(transcript.source.model, "small")
                self.assertGreater(len(transcript.words), 0)
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
                self.assertEqual(response, original)

        self.assertEqual(transcripts[0].source.provider, "mlx-whisper")
        self.assertEqual(transcripts[1].source.provider, "open-source-whisper")
        self.assertNotEqual(transcripts[0].transcript_id, transcripts[1].transcript_id)
        self.assertEqual(
            _content_projection(transcripts[0]),
            _content_projection(transcripts[1]),
        )

    def test_both_providers_reject_empty_word_results(self) -> None:
        response: dict[str, object] = {
            "text": "",
            "language": "zh",
            "segments": [],
        }

        for provider in ("mlx", "open-source"):
            with self.subTest(provider=provider):
                with self.assertRaisesRegex(ProcessingError, "no timestamped words"):
                    _map_provider(provider, response)

    def test_both_providers_reject_incomplete_word_timestamps(self) -> None:
        for provider in ("mlx", "open-source"):
            with self.subTest(provider=provider):
                response = _raw_whisper_response()
                segments = cast(list[dict[str, object]], response["segments"])
                words = cast(list[dict[str, object]], segments[0]["words"])
                words[0].pop("end")

                with self.assertRaisesRegex(
                    ProcessingError,
                    "invalid or incomplete word timestamps",
                ):
                    _map_provider(provider, response)


if __name__ == "__main__":
    unittest.main()
