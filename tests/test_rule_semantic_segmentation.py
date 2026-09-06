import unittest

from minicut.semantic_segmentation import build_rule_based_segments
from minicut.transcript import Transcript, TranscriptSource, Utterance, Word


def _transcript() -> Transcript:
    return Transcript(
        transcript_id="transcript-1",
        source=TranscriptSource("asset-1", "mlx-whisper", "large-v3-turbo"),
        language="zh",
        words=(
            Word("word-1", "第一句。", 0, 500),
            Word("word-2", "Second", 600, 850),
            Word("word-3", "sentence.", 900, 1_200),
        ),
    )


def _utterances() -> tuple[Utterance, ...]:
    return (
        Utterance("utterance-1", "第一句。", 0, 500, ("word-1",)),
        Utterance(
            "utterance-2",
            "Second sentence.",
            600,
            1_200,
            ("word-2", "word-3"),
        ),
    )


class RuleSemanticSegmentationTest(unittest.TestCase):
    def test_each_utterance_becomes_a_traceable_segment(self) -> None:
        transcript = _transcript()
        original = transcript.to_dict()

        segments = build_rule_based_segments(transcript, _utterances())

        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0].segment_id, "segment:transcript-1:0")
        self.assertEqual(segments[0].text, "第一句。")
        self.assertEqual((segments[0].start_ms, segments[0].end_ms), (0, 500))
        self.assertEqual(segments[0].utterance_ids, ("utterance-1",))
        self.assertEqual(segments[0].word_ids, ("word-1",))
        self.assertEqual(segments[0].context_dependencies, ())
        self.assertEqual(segments[1].segment_id, "segment:transcript-1:1")
        self.assertEqual(segments[1].word_ids, ("word-2", "word-3"))
        self.assertEqual(transcript.to_dict(), original)

    def test_same_input_produces_the_same_segments(self) -> None:
        transcript = _transcript()

        first = build_rule_based_segments(transcript, _utterances())
        second = build_rule_based_segments(transcript, _utterances())

        self.assertEqual(second, first)

    def test_empty_transcript_and_utterances_produce_no_segments(self) -> None:
        transcript = Transcript(
            "transcript-empty",
            TranscriptSource("asset-1", "mlx-whisper", "large-v3-turbo"),
            "zh",
        )

        self.assertEqual(build_rule_based_segments(transcript, ()), ())

    def test_utterances_must_cover_words_once_in_source_order(self) -> None:
        transcript = _transcript()
        invalid_utterances = (
            _utterances()[:1],
            (
                Utterance(
                    "utterance-1",
                    "重复",
                    0,
                    850,
                    ("word-1", "word-2", "word-2"),
                ),
                Utterance("utterance-2", "末句", 900, 1_200, ("word-3",)),
            ),
            tuple(reversed(_utterances())),
            (Utterance("utterance-1", "未知", 0, 500, ("missing",)),),
        )

        for utterances in invalid_utterances:
            with self.subTest(utterances=utterances):
                with self.assertRaisesRegex(ValueError, "coverage"):
                    build_rule_based_segments(transcript, utterances)

    def test_utterance_ids_must_be_unique(self) -> None:
        first, second = _utterances()
        duplicate_id = Utterance(
            first.utterance_id,
            second.text,
            second.start_ms,
            second.end_ms,
            second.word_ids,
        )

        with self.assertRaisesRegex(ValueError, "Utterance IDs"):
            build_rule_based_segments(_transcript(), (first, duplicate_id))

    def test_utterance_ranges_must_not_overlap(self) -> None:
        first, second = _utterances()
        overlapping_first = Utterance(
            first.utterance_id,
            first.text,
            first.start_ms,
            700,
            first.word_ids,
        )

        with self.assertRaisesRegex(ValueError, "overlap"):
            build_rule_based_segments(
                _transcript(),
                (overlapping_first, second),
            )

    def test_blank_utterance_text_is_rejected_instead_of_dropped(self) -> None:
        first, second = _utterances()
        blank_first = Utterance(
            first.utterance_id,
            "  ",
            first.start_ms,
            first.end_ms,
            first.word_ids,
        )

        with self.assertRaisesRegex(ValueError, "text"):
            build_rule_based_segments(_transcript(), (blank_first, second))


if __name__ == "__main__":
    unittest.main()
