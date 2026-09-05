import unittest

from minicut.transcript import (
    TRANSCRIPT_SCHEMA_VERSION,
    Transcript,
    TranscriptSource,
    Utterance,
    Word,
)


class TranscriptModelTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
