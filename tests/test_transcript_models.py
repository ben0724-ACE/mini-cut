import json
import unittest
from typing import cast

from minicut.transcript import (
    TRANSCRIPT_SCHEMA_VERSION,
    Transcript,
    TranscriptSource,
    Utterance,
    Word,
    generate_transcript_id,
    generate_utterance_id,
    generate_word_id,
)


class TranscriptModelTest(unittest.TestCase):
    @staticmethod
    def _source() -> TranscriptSource:
        return TranscriptSource("asset-1", "mlx-whisper", "large-v3-turbo")

    def test_transcript_composes_source_words_and_utterances(self) -> None:
        source = TranscriptSource(
            asset_id="asset-1",
            provider="mlx-whisper",
            model="large-v3-turbo",
        )
        word = Word(
            word_id="word-1",
            text="你好",
            start_ms=100,
            end_ms=420,
            probability=0.97,
        )
        utterance = Utterance(
            utterance_id="utterance-1",
            text="你好",
            start_ms=100,
            end_ms=420,
            word_ids=(word.word_id,),
            speaker="speaker-1",
        )

        transcript = Transcript(
            transcript_id="transcript-1",
            source=source,
            language="zh",
            words=(word,),
            utterances=(utterance,),
        )

        self.assertEqual(transcript.source, source)
        self.assertEqual(transcript.words, (word,))
        self.assertEqual(transcript.utterances, (utterance,))
        self.assertEqual(transcript.schema_version, TRANSCRIPT_SCHEMA_VERSION)

    def test_transcript_supports_empty_results_and_unknown_word_probability(
        self,
    ) -> None:
        transcript = Transcript(
            transcript_id="transcript-1",
            source=TranscriptSource("asset-1", "mlx-whisper", "large-v3-turbo"),
            language="zh",
        )
        word = Word("word-1", "嗯", 0, 100)

        self.assertEqual(transcript.words, ())
        self.assertEqual(transcript.utterances, ())
        self.assertIsNone(word.probability)

    def test_word_rejects_probability_outside_zero_to_one(self) -> None:
        for probability in (-0.01, 1.01):
            with self.subTest(probability=probability):
                with self.assertRaisesRegex(ValueError, "probability"):
                    Word("word-1", "你好", 0, 100, probability)

    def test_word_and_utterance_reject_invalid_time_ranges(self) -> None:
        invalid_ranges = ((-1, 100), (100, 100), (200, 100))

        for start_ms, end_ms in invalid_ranges:
            with self.subTest(model="word", start_ms=start_ms, end_ms=end_ms):
                with self.assertRaisesRegex(ValueError, "Word time range"):
                    Word("word-1", "你好", start_ms, end_ms)
            with self.subTest(model="utterance", start_ms=start_ms, end_ms=end_ms):
                with self.assertRaisesRegex(ValueError, "Utterance time range"):
                    Utterance(
                        "utterance-1",
                        "你好",
                        start_ms,
                        end_ms,
                        ("word-1",),
                    )

    def test_transcript_rejects_word_time_regression(self) -> None:
        regressing_words = (
            (
                Word("word-1", "你", 100, 300),
                Word("word-2", "好", 90, 400),
            ),
            (
                Word("word-1", "你", 100, 300),
                Word("word-2", "好", 200, 250),
            ),
        )

        for words in regressing_words:
            with self.subTest(words=words):
                with self.assertRaisesRegex(ValueError, "monotonic"):
                    Transcript("transcript-1", self._source(), "zh", words=words)

    def test_transcript_allows_monotonic_overlapping_words(self) -> None:
        words = (
            Word("word-1", "你", 0, 200),
            Word("word-2", "好", 150, 300),
        )

        transcript = Transcript("transcript-1", self._source(), "zh", words=words)

        self.assertEqual(transcript.words, words)

    def test_utterance_rejects_an_unknown_word_reference(self) -> None:
        utterance = Utterance("utterance-1", "你好", 0, 300, ("missing",))

        with self.assertRaisesRegex(ValueError, "unknown Word ID"):
            Transcript(
                "transcript-1",
                self._source(),
                "zh",
                utterances=(utterance,),
            )

    def test_utterance_must_contain_each_referenced_word(self) -> None:
        word = Word("word-1", "你好", 100, 300)
        outside_ranges = ((150, 350), (50, 250))

        for start_ms, end_ms in outside_ranges:
            utterance = Utterance(
                "utterance-1",
                "你好",
                start_ms,
                end_ms,
                (word.word_id,),
            )
            with self.subTest(start_ms=start_ms, end_ms=end_ms):
                with self.assertRaisesRegex(ValueError, "must contain"):
                    Transcript(
                        "transcript-1",
                        self._source(),
                        "zh",
                        words=(word,),
                        utterances=(utterance,),
                    )


class StableTranscriptIdTest(unittest.TestCase):
    def test_same_normalized_input_produces_the_same_ids(self) -> None:
        source = TranscriptSource("asset-1", "mlx-whisper", "large-v3-turbo")

        first_transcript_id = generate_transcript_id(source, "zh")
        first_word_id = generate_word_id(
            first_transcript_id,
            0,
            text="你好",
            start_ms=100,
            end_ms=420,
        )
        first_utterance_id = generate_utterance_id(
            first_transcript_id,
            0,
            text="你好",
            start_ms=100,
            end_ms=420,
            word_ids=(first_word_id,),
            speaker="speaker-1",
        )

        second_transcript_id = generate_transcript_id(source, "zh")
        second_word_id = generate_word_id(
            second_transcript_id,
            0,
            text="你好",
            start_ms=100,
            end_ms=420,
        )
        second_utterance_id = generate_utterance_id(
            second_transcript_id,
            0,
            text="你好",
            start_ms=100,
            end_ms=420,
            word_ids=(second_word_id,),
            speaker="speaker-1",
        )

        self.assertEqual(second_transcript_id, first_transcript_id)
        self.assertEqual(second_word_id, first_word_id)
        self.assertEqual(second_utterance_id, first_utterance_id)
        for stable_id in (first_transcript_id, first_word_id, first_utterance_id):
            self.assertNotIn("你好", stable_id)
            self.assertNotIn("large-v3-turbo", stable_id)

    def test_meaningful_normalized_word_changes_produce_different_ids(self) -> None:
        transcript_id = generate_transcript_id(
            TranscriptSource("asset-1", "mlx-whisper", "large-v3-turbo"),
            "zh",
        )
        original = generate_word_id(
            transcript_id,
            0,
            text="你好",
            start_ms=100,
            end_ms=420,
        )
        changed_ids = (
            generate_word_id(
                transcript_id,
                1,
                text="你好",
                start_ms=100,
                end_ms=420,
            ),
            generate_word_id(
                transcript_id,
                0,
                text="您好",
                start_ms=100,
                end_ms=420,
            ),
            generate_word_id(
                transcript_id,
                0,
                text="你好",
                start_ms=110,
                end_ms=420,
            ),
        )

        for changed_id in changed_ids:
            with self.subTest(changed_id=changed_id):
                self.assertNotEqual(changed_id, original)

    def test_word_and_utterance_ids_reject_negative_ordinals(self) -> None:
        with self.assertRaisesRegex(ValueError, "ordinal"):
            generate_word_id(
                "transcript-1",
                -1,
                text="你好",
                start_ms=100,
                end_ms=420,
            )
        with self.assertRaisesRegex(ValueError, "ordinal"):
            generate_utterance_id(
                "transcript-1",
                -1,
                text="你好",
                start_ms=100,
                end_ms=420,
                word_ids=("word-1",),
            )

    def test_transcript_and_utterance_inputs_distinguish_ids(self) -> None:
        source = TranscriptSource("asset-1", "mlx-whisper", "large-v3-turbo")
        transcript_id = generate_transcript_id(source, "zh")

        self.assertNotEqual(
            generate_transcript_id(source, "en"),
            transcript_id,
        )
        self.assertNotEqual(
            generate_transcript_id(
                TranscriptSource("asset-2", "mlx-whisper", "large-v3-turbo"),
                "zh",
            ),
            transcript_id,
        )

        original = generate_utterance_id(
            transcript_id,
            0,
            text="你好",
            start_ms=100,
            end_ms=420,
            word_ids=("word-1",),
        )
        changed = generate_utterance_id(
            transcript_id,
            0,
            text="你好",
            start_ms=100,
            end_ms=420,
            word_ids=("word-1",),
            speaker="speaker-1",
        )

        self.assertNotEqual(changed, original)


class TranscriptSerializationTest(unittest.TestCase):
    @staticmethod
    def _transcript(*, probability: float | None = 0.97) -> Transcript:
        source = TranscriptSource("asset-1", "mlx-whisper", "large-v3-turbo")
        word = Word("word-1", "你好", 100, 420, probability)
        utterance = Utterance(
            "utterance-1",
            "你好",
            100,
            420,
            (word.word_id,),
            "speaker-1",
        )
        return Transcript(
            "transcript-1",
            source,
            "zh",
            words=(word,),
            utterances=(utterance,),
        )

    def test_transcript_round_trips_through_json_with_nested_models(self) -> None:
        transcript = self._transcript()

        encoded = json.dumps(transcript.to_dict(), ensure_ascii=False)
        decoded = cast(dict[str, object], json.loads(encoded))
        decoded["future_optional_field"] = {"ignored": True}
        restored = Transcript.from_dict(decoded)

        self.assertEqual(restored, transcript)

    def test_transcript_round_trip_preserves_empty_and_optional_values(self) -> None:
        transcript = Transcript(
            "transcript-1",
            TranscriptSource("asset-1", "mlx-whisper", "large-v3-turbo"),
            "zh",
            words=(Word("word-1", "嗯", 0, 100, None),),
        )

        decoded = cast(
            dict[str, object],
            json.loads(json.dumps(transcript.to_dict(), ensure_ascii=False)),
        )

        self.assertEqual(Transcript.from_dict(decoded), transcript)

    def test_transcript_rejects_unknown_schema_with_migration_hint(self) -> None:
        for schema_version in (TRANSCRIPT_SCHEMA_VERSION + 1, "1", 1.0, True):
            data = self._transcript().to_dict()
            data["schema_version"] = schema_version

            with self.subTest(schema_version=schema_version):
                with self.assertRaisesRegex(ValueError, "Migrate.*schema version 1"):
                    Transcript.from_dict(data)


if __name__ == "__main__":
    unittest.main()
