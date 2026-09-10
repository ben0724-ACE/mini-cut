import unittest

from minicut.media import TimeRange
from minicut.semantic_segment import SemanticSegment
from minicut.subtitle import map_retained_words
from minicut.timeline import Clip, Timeline
from minicut.transcript import Word


def _segment(
    segment_id: str,
    word_ids: tuple[str, ...],
    start_ms: int,
    end_ms: int,
) -> SemanticSegment:
    return SemanticSegment(
        segment_id,
        segment_id,
        start_ms,
        end_ms,
        (f"utterance:{segment_id}",),
        word_ids,
    )


class RetainedWordMappingTest(unittest.TestCase):
    def test_maps_retained_words_across_clips_and_excludes_deleted_padding(
        self,
    ) -> None:
        words = (
            Word("deleted", "删除", 50, 90),
            Word("w1", "第一", 100, 300),
            Word("w2", "句", 350, 500),
            Word("w3", "结尾", 1_100, 1_400),
        )
        segments = (
            _segment("s1", ("w1", "w2"), 100, 500),
            _segment("s2", ("w3",), 1_100, 1_400),
        )
        timeline = Timeline(
            (
                Clip(
                    "clip:0",
                    "asset-1",
                    "s1",
                    TimeRange(50, 550),
                    TimeRange(0, 500),
                ),
                Clip(
                    "clip:1",
                    "asset-1",
                    "s2",
                    TimeRange(1_050, 1_450),
                    TimeRange(500, 900),
                ),
            ),
            900,
        )

        mapped = map_retained_words(timeline, segments, words)

        self.assertEqual(tuple(word.word_id for word in mapped), ("w1", "w2", "w3"))
        self.assertEqual(
            tuple((word.start_ms, word.end_ms) for word in mapped),
            ((50, 250), (300, 450), (550, 850)),
        )
        self.assertTrue(
            all(word.end_ms <= timeline.estimated_duration_ms for word in mapped)
        )

    def test_merged_clip_maps_words_from_every_retained_segment(self) -> None:
        words = (Word("w1", "A", 100, 200), Word("w2", "B", 400, 500))
        segments = (
            _segment("s1", ("w1",), 100, 200),
            _segment("s2", ("w2",), 400, 500),
        )
        timeline = Timeline(
            (
                Clip(
                    "clip:0",
                    "asset-1",
                    "s1",
                    TimeRange(100, 500),
                    TimeRange(0, 400),
                    ("s1", "s2"),
                ),
            ),
            400,
        )

        mapped = map_retained_words(timeline, segments, words)

        self.assertEqual(tuple(word.text for word in mapped), ("A", "B"))
        self.assertEqual(tuple(word.clip_id for word in mapped), ("clip:0", "clip:0"))

    def test_rejects_broken_references_ranges_and_duplicate_mapping(self) -> None:
        word = Word("w1", "内容", 100, 200)
        valid_segment = _segment("s1", ("w1",), 100, 200)
        cases = (
            (
                (_segment("other", ("w1",), 100, 200),),
                (word,),
                TimeRange(100, 200),
                ("s1",),
                "unknown Segment",
            ),
            (
                (_segment("s1", ("missing",), 100, 200),),
                (word,),
                TimeRange(100, 200),
                ("s1",),
                "unknown Word",
            ),
            (
                (valid_segment,),
                (word,),
                TimeRange(120, 220),
                ("s1",),
                "outside",
            ),
            (
                (valid_segment,),
                (word,),
                TimeRange(100, 200),
                ("s1", "s1"),
                "more than one Clip",
            ),
        )
        for segments, words, source_range, clip_segments, message in cases:
            with self.subTest(message=message):
                clips = tuple(
                    Clip(
                        f"clip:{index}",
                        "asset-1",
                        segment_id,
                        source_range,
                        TimeRange(index * 100, index * 100 + 100),
                    )
                    for index, segment_id in enumerate(clip_segments)
                )
                with self.assertRaisesRegex(ValueError, message):
                    map_retained_words(
                        Timeline(clips, len(clips) * 100),
                        segments,
                        words,
                    )


if __name__ == "__main__":
    unittest.main()
