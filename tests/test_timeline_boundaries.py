import unittest

from minicut.media import TimeRange
from minicut.semantic_segment import SemanticSegment
from minicut.timeline import Clip, Timeline
from minicut.timeline_boundary import (
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


if __name__ == "__main__":
    unittest.main()
