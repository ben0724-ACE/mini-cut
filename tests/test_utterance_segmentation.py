import unittest

from minicut.segmentation import (
    SegmentationPolicy,
    build_utterances,
    build_utterances_by_pause,
)
from minicut.text_normalization import WordTextMapping
from minicut.transcript import (
    Transcript,
    TranscriptSource,
    Word,
    generate_utterance_id,
)


def _transcript(words: tuple[Word, ...]) -> Transcript:
    return Transcript(
        transcript_id="transcript-1",
        source=TranscriptSource("asset-1", "mlx-whisper", "large-v3-turbo"),
        language="zh",
        words=words,
    )


def _mappings(words: tuple[Word, ...]) -> tuple[WordTextMapping, ...]:
    return tuple(WordTextMapping(word.word_id, word.text, word.text) for word in words)


class SegmentationPolicyTest(unittest.TestCase):
    def test_defaults_capture_the_initial_d2_thresholds(self) -> None:
        policy = SegmentationPolicy()

        self.assertEqual(policy.pause_threshold_ms, 800)
        self.assertEqual(policy.min_duration_ms, 1_000)
        self.assertEqual(policy.max_duration_ms, 15_000)

    def test_invalid_thresholds_are_rejected(self) -> None:
        invalid_values = (
            {"pause_threshold_ms": 0},
            {"min_duration_ms": 0},
            {"min_duration_ms": 2_000, "max_duration_ms": 1_999},
        )

        for values in invalid_values:
            with self.subTest(values=values):
                with self.assertRaisesRegex(ValueError, "threshold|duration"):
                    SegmentationPolicy(**values)


class PauseSegmentationTest(unittest.TestCase):
    def test_pause_at_threshold_starts_a_new_utterance(self) -> None:
        words = (
            Word("word-1", "你", 100, 300),
            Word("word-2", "好", 500, 700),
            Word("word-3", "world", 1_499, 1_700),
            Word("word-4", "！", 2_500, 2_600),
        )
        transcript = _transcript(words)

        utterances = build_utterances_by_pause(transcript, _mappings(words))

        first_word_ids = ("word-1", "word-2", "word-3")
        self.assertEqual(len(utterances), 2)
        self.assertEqual(utterances[0].text, "你好 world")
        self.assertEqual(utterances[0].start_ms, 100)
        self.assertEqual(utterances[0].end_ms, 1_700)
        self.assertEqual(utterances[0].word_ids, first_word_ids)
        self.assertEqual(
            utterances[0].utterance_id,
            generate_utterance_id(
                transcript.transcript_id,
                0,
                text="你好 world",
                start_ms=100,
                end_ms=1_700,
                word_ids=first_word_ids,
            ),
        )
        self.assertEqual(utterances[1].text, "！")
        self.assertEqual(utterances[1].word_ids, ("word-4",))

    def test_custom_pause_threshold_controls_grouping(self) -> None:
        words = (
            Word("word-1", "first", 0, 100),
            Word("word-2", "second", 600, 700),
        )
        transcript = _transcript(words)

        split = build_utterances_by_pause(
            transcript,
            _mappings(words),
            policy=SegmentationPolicy(pause_threshold_ms=500),
        )
        joined = build_utterances_by_pause(
            transcript,
            _mappings(words),
            policy=SegmentationPolicy(pause_threshold_ms=501),
        )

        self.assertEqual(len(split), 2)
        self.assertEqual(len(joined), 1)
        self.assertEqual(joined[0].text, "first second")

    def test_empty_transcript_produces_no_utterances(self) -> None:
        self.assertEqual(build_utterances_by_pause(_transcript(()), ()), ())

    def test_mappings_must_align_with_transcript_words(self) -> None:
        words = (Word("word-1", "你好", 0, 100),)

        with self.assertRaisesRegex(ValueError, "align"):
            build_utterances_by_pause(
                _transcript(words),
                (WordTextMapping("another-word", "你好", "你好"),),
            )


class UtteranceBoundaryTest(unittest.TestCase):
    def test_chinese_and_english_terminal_punctuation_end_an_utterance(
        self,
    ) -> None:
        for terminator in ("。", "！", "？", ".", "!", "?"):
            with self.subTest(terminator=terminator):
                words = (
                    Word("word-1", f"first{terminator}", 0, 400),
                    Word("word-2", "next", 500, 800),
                )

                utterances = build_utterances(_transcript(words), _mappings(words))

                self.assertEqual(
                    tuple(utterance.word_ids for utterance in utterances),
                    (("word-1",), ("word-2",)),
                )

    def test_non_terminal_punctuation_does_not_force_a_split(self) -> None:
        words = (
            Word("word-1", "however,", 0, 400),
            Word("word-2", "continue", 500, 800),
        )

        utterances = build_utterances(_transcript(words), _mappings(words))

        self.assertEqual(len(utterances), 1)
        self.assertEqual(utterances[0].text, "however, continue")

    def test_exact_maximum_is_allowed_and_excess_starts_a_new_group(self) -> None:
        words = (
            Word("word-1", "one", 0, 500),
            Word("word-2", "two", 600, 1_500),
            Word("word-3", "three", 1_600, 1_700),
        )
        policy = SegmentationPolicy(min_duration_ms=100, max_duration_ms=1_500)

        utterances = build_utterances(
            _transcript(words),
            _mappings(words),
            policy=policy,
        )

        self.assertEqual(
            tuple(utterance.word_ids for utterance in utterances),
            (("word-1", "word-2"), ("word-3",)),
        )

    def test_single_word_longer_than_maximum_remains_atomic(self) -> None:
        words = (
            Word("word-1", "extraordinary", 0, 2_000),
            Word("word-2", "next", 2_100, 2_300),
        )
        policy = SegmentationPolicy(min_duration_ms=100, max_duration_ms=1_500)

        utterances = build_utterances(
            _transcript(words),
            _mappings(words),
            policy=policy,
        )

        self.assertEqual(utterances[0].word_ids, ("word-1",))
        self.assertEqual(utterances[0].end_ms - utterances[0].start_ms, 2_000)


if __name__ == "__main__":
    unittest.main()
