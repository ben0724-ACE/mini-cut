import unittest

from minicut.transcript import (
    TRANSCRIPT_SCHEMA_VERSION,
    Transcript,
    TranscriptSource,
    Utterance,
    Word,
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


if __name__ == "__main__":
    unittest.main()
