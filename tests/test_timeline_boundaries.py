import unittest

from minicut.media import TimeRange
from minicut.semantic_segment import SemanticSegment
from minicut.timeline import Clip, Timeline
from minicut.timeline_boundary import (
    BoundaryPolicy,
    apply_boundary_padding,
    protect_word_and_punctuation_boundaries,
    snap_clip_end_boundaries,
    snap_clip_start_boundaries,
)
from minicut.transcript import Word


def _segment(
    ordinal: int,
    word_ids: tuple[str, ...],
    start_ms: int,
    end_ms: int,
) -> SemanticSegment:
    return SemanticSegment(
        segment_id=f"segment-{ordinal}",
        text=f"内容 {ordinal}",
        start_ms=start_ms,
        end_ms=end_ms,
        utterance_ids=(f"utterance-{ordinal}",),
        word_ids=word_ids,
    )


def _clip(
    ordinal: int,
    source_range: TimeRange,
    output_range: TimeRange,
) -> Clip:
    return Clip(
        f"clip:{ordinal}",
        "asset-1",
        f"segment-{ordinal}",
        source_range,
        output_range,
    )


class SnapClipStartBoundariesTest(unittest.TestCase):
    def test_snaps_each_start_to_earliest_referenced_word_and_reflows_output(
        self,
    ) -> None:
        segments = (
            _segment(0, ("word-0", "word-1"), 900, 2_100),
            _segment(1, ("word-2",), 3_000, 4_000),
        )
        words = (
            Word("word-0", "第一", 1_000, 1_300),
            Word("word-1", "句话", 1_600, 2_000),
            Word("word-2", "结尾", 3_200, 3_800),
        )
        timeline = Timeline(
            (
                _clip(0, TimeRange(900, 2_100), TimeRange(0, 1_200)),
                _clip(1, TimeRange(3_000, 4_000), TimeRange(1_200, 2_200)),
            ),
            2_200,
        )

        refined = snap_clip_start_boundaries(timeline, segments, words)

        self.assertEqual(
            tuple(clip.source_range for clip in refined.clips),
            (TimeRange(1_000, 2_100), TimeRange(3_200, 4_000)),
        )
        self.assertEqual(
            tuple(clip.output_range for clip in refined.clips),
            (TimeRange(0, 1_100), TimeRange(1_100, 1_900)),
        )
        self.assertEqual(refined.estimated_duration_ms, 1_900)

    def test_rejects_unknown_clip_segment_or_referenced_word(self) -> None:
        timeline = Timeline(
            (_clip(0, TimeRange(900, 2_100), TimeRange(0, 1_200)),),
            1_200,
        )
        word = Word("word-0", "内容", 1_000, 2_000)
        invalid_inputs = (
            (
                (_segment(1, ("word-0",), 900, 2_100),),
                (word,),
                "unknown Segment",
            ),
            (
                (_segment(0, ("missing",), 900, 2_100),),
                (word,),
                "unknown Word",
            ),
        )

        for segments, words, message in invalid_inputs:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    snap_clip_start_boundaries(timeline, segments, words)


class SnapClipEndBoundariesTest(unittest.TestCase):
    def test_snaps_each_end_to_latest_referenced_word_and_reflows_output(
        self,
    ) -> None:
        segments = (
            _segment(0, ("word-0", "word-1"), 900, 2_100),
            _segment(1, ("word-2",), 3_000, 4_000),
        )
        words = (
            Word("word-0", "第一", 1_000, 1_300),
            Word("word-1", "句话", 1_600, 2_000),
            Word("word-2", "结尾", 3_200, 3_800),
        )
        timeline = Timeline(
            (
                _clip(0, TimeRange(1_000, 2_100), TimeRange(0, 1_100)),
                _clip(1, TimeRange(3_200, 4_000), TimeRange(1_100, 1_900)),
            ),
            1_900,
        )

        refined = snap_clip_end_boundaries(timeline, segments, words)

        self.assertEqual(
            tuple(clip.source_range for clip in refined.clips),
            (TimeRange(1_000, 2_000), TimeRange(3_200, 3_800)),
        )
        self.assertEqual(
            tuple(clip.output_range for clip in refined.clips),
            (TimeRange(0, 1_000), TimeRange(1_000, 1_600)),
        )
        self.assertEqual(refined.estimated_duration_ms, 1_600)

    def test_end_snap_reuses_reference_validation(self) -> None:
        timeline = Timeline(
            (_clip(0, TimeRange(1_000, 2_100), TimeRange(0, 1_100)),),
            1_100,
        )
        segments = (_segment(0, ("missing",), 900, 2_100),)

        with self.assertRaisesRegex(ValueError, "unknown Word"):
            snap_clip_end_boundaries(
                timeline,
                segments,
                (Word("word-0", "内容", 1_000, 2_000),),
            )


class BoundaryPaddingTest(unittest.TestCase):
    def test_table_driven_padding_clamps_media_and_avoids_overlap(self) -> None:
        cases = (
            (
                "media edges",
                (TimeRange(100, 500), TimeRange(1_600, 1_900)),
                BoundaryPolicy(200, 200),
                2_000,
                (TimeRange(0, 700), TimeRange(1_400, 2_000)),
            ),
            (
                "padding collision",
                (TimeRange(100, 500), TimeRange(600, 900)),
                BoundaryPolicy(200, 200),
                1_000,
                (TimeRange(0, 550), TimeRange(550, 1_000)),
            ),
            (
                "available gap",
                (TimeRange(500, 1_000), TimeRange(1_500, 2_000)),
                BoundaryPolicy(100, 100),
                3_000,
                (TimeRange(400, 1_100), TimeRange(1_400, 2_100)),
            ),
        )

        for name, source_ranges, policy, media_duration_ms, expected in cases:
            with self.subTest(name=name):
                timeline = Timeline(
                    tuple(
                        _clip(
                            ordinal,
                            source_range,
                            TimeRange(ordinal * 400, ordinal * 400 + 400),
                        )
                        for ordinal, source_range in enumerate(source_ranges)
                    ),
                    800,
                )

                padded = apply_boundary_padding(timeline, policy, media_duration_ms)

                self.assertEqual(
                    tuple(clip.source_range for clip in padded.clips), expected
                )
                self.assertTrue(
                    all(
                        left.source_range.end_ms <= right.source_range.start_ms
                        for left, right in zip(
                            padded.clips, padded.clips[1:], strict=False
                        )
                    )
                )
                self.assertEqual(
                    padded.estimated_duration_ms,
                    sum(time_range.duration_ms for time_range in expected),
                )

    def test_rejects_invalid_policy_media_or_preexisting_overlap(self) -> None:
        invalid_factories = (
            lambda: BoundaryPolicy(-1, 0),
            lambda: BoundaryPolicy(0, -1),
        )
        for create_policy in invalid_factories:
            with self.subTest(create_policy=create_policy):
                with self.assertRaises(ValueError):
                    create_policy()

        timeline = Timeline(
            (
                _clip(0, TimeRange(100, 600), TimeRange(0, 500)),
                _clip(1, TimeRange(500, 900), TimeRange(500, 900)),
            ),
            900,
        )
        with self.assertRaisesRegex(ValueError, "overlap"):
            apply_boundary_padding(timeline, BoundaryPolicy(100, 100), 1_000)
        with self.assertRaisesRegex(ValueError, "media duration"):
            apply_boundary_padding(timeline, BoundaryPolicy(0, 0), 0)


class WordAndPunctuationProtectionTest(unittest.TestCase):
    def test_table_driven_word_boundary_protection(self) -> None:
        cases = (
            (
                "exclude partial neighboring words",
                TimeRange(50, 250),
                (_segment(0, ("owned",), 100, 200),),
                (
                    Word("previous", "前", 0, 80),
                    Word("owned", "内容", 100, 200),
                    Word("next", "后", 230, 300),
                ),
                TimeRange(80, 230),
            ),
            (
                "preserve complete owned word",
                TimeRange(120, 180),
                (_segment(0, ("owned",), 100, 200),),
                (Word("owned", "完整", 100, 200),),
                TimeRange(100, 200),
            ),
        )

        for name, source_range, segments, words, expected in cases:
            with self.subTest(name=name):
                timeline = Timeline(
                    (_clip(0, source_range, TimeRange(0, source_range.duration_ms)),),
                    source_range.duration_ms,
                )

                protected = protect_word_and_punctuation_boundaries(
                    timeline, segments, words, 1_000
                )

                self.assertEqual(protected.clips[0].source_range, expected)
                self.assertEqual(protected.estimated_duration_ms, expected.duration_ms)

    def test_attaches_unowned_punctuation_but_not_the_next_word(self) -> None:
        segments = (_segment(0, ("owned",), 100, 200),)
        words = (
            Word("owned", "你好", 100, 200),
            Word("comma", "，", 200, 230),
            Word("quote", "”", 230, 250),
            Word("next", "下一句", 260, 400),
        )
        timeline = Timeline((_clip(0, TimeRange(100, 200), TimeRange(0, 100)),), 100)

        protected = protect_word_and_punctuation_boundaries(
            timeline, segments, words, 1_000
        )

        self.assertEqual(protected.clips[0].source_range, TimeRange(100, 250))
        self.assertEqual(protected.estimated_duration_ms, 150)

    def test_rejects_overlap_instead_of_cutting_a_protected_word(self) -> None:
        segments = (
            _segment(0, ("word-0",), 100, 300),
            _segment(1, ("word-1",), 250, 450),
        )
        words = (
            Word("word-0", "前词", 100, 300),
            Word("word-1", "后词", 250, 450),
        )
        timeline = Timeline(
            (
                _clip(0, TimeRange(100, 280), TimeRange(0, 180)),
                _clip(1, TimeRange(270, 450), TimeRange(180, 360)),
            ),
            360,
        )

        with self.assertRaisesRegex(ValueError, "protected boundaries overlap"):
            protect_word_and_punctuation_boundaries(timeline, segments, words, 1_000)

    def test_rejects_protection_beyond_media_duration(self) -> None:
        segments = (_segment(0, ("owned",), 800, 950),)
        words = (
            Word("owned", "结尾", 800, 950),
            Word("punctuation", "。", 950, 1_010),
        )
        timeline = Timeline((_clip(0, TimeRange(800, 950), TimeRange(0, 150)),), 150)

        with self.assertRaisesRegex(ValueError, "media duration"):
            protect_word_and_punctuation_boundaries(timeline, segments, words, 1_000)


if __name__ == "__main__":
    unittest.main()
