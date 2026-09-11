import unittest

from minicut.media import TimeRange
from minicut.semantic_segment import SemanticSegment
from minicut.subtitle import (
    MappedWord,
    SubtitleCue,
    SubtitleLayoutPolicy,
    build_readable_cues,
    build_word_cues,
    map_retained_words,
    parse_srt,
    render_srt,
)
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


class SrtSerializationTest(unittest.TestCase):
    def test_word_cues_render_as_valid_srt_and_round_trip(self) -> None:
        words = (
            MappedWord("w1", "你好", 0, 450, "clip:0"),
            MappedWord("w2", "MiniCut", 500, 1_200, "clip:0"),
            MappedWord("w3", "结束", 3_723_456, 3_724_000, "clip:1"),
        )

        cues = build_word_cues(words, 3_724_000)
        content = render_srt(cues, 3_724_000)

        self.assertEqual(
            content,
            "1\n00:00:00,000 --> 00:00:00,450\n你好\n\n"
            "2\n00:00:00,500 --> 00:00:01,200\nMiniCut\n\n"
            "3\n01:02:03,456 --> 01:02:04,000\n结束\n",
        )
        self.assertEqual(parse_srt(content), cues)
        self.assertEqual(parse_srt(content.replace("\n", "\r\n")), cues)

    def test_rejects_overlap_or_cue_beyond_video_duration(self) -> None:
        cases = (
            (
                (
                    SubtitleCue(0, 500, "first"),
                    SubtitleCue(400, 700, "second"),
                ),
                1_000,
                "non-overlapping",
            ),
            ((SubtitleCue(0, 1_001, "too long"),), 1_000, "exceeds"),
        )
        for cues, duration_ms, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    render_srt(cues, duration_ms)

    def test_parser_rejects_invalid_index_timestamp_and_timing_separator(self) -> None:
        invalid = (
            "2\n00:00:00,000 --> 00:00:01,000\ntext\n",
            "1\n00:00:60,000 --> 00:01:01,000\ntext\n",
            "1\n00:00:00,000 -> 00:00:01,000\ntext\n",
        )
        for content in invalid:
            with self.subTest(content=content):
                with self.assertRaises(ValueError):
                    parse_srt(content)


class ReadableSubtitleLayoutTest(unittest.TestCase):
    def test_keeps_chinese_punctuation_with_text_without_exceeding_line_limit(
        self,
    ) -> None:
        words = (
            MappedWord("w1", "一二三四", 0, 200, "clip:0"),
            MappedWord("w2", "五六", 220, 400, "clip:0"),
            MappedWord("w3", ",", 400, 450, "clip:0"),
        )

        cues = build_readable_cues(
            words,
            1_000,
            SubtitleLayoutPolicy(
                max_characters_per_line=6,
                max_lines=2,
                min_duration_ms=100,
                max_duration_ms=2_000,
                normalize_chinese_punctuation=True,
            ),
        )

        self.assertEqual(cues[0].text, "一二三四\n五六，")
        self.assertTrue(all(len(line) <= 6 for line in cues[0].text.splitlines()))

    def test_preserves_ascii_punctuation_in_english_text(self) -> None:
        words = (
            MappedWord("w1", "hello", 0, 200, "clip:0"),
            MappedWord("w2", ",", 200, 220, "clip:0"),
            MappedWord("w3", "world", 240, 500, "clip:0"),
        )

        cues = build_readable_cues(words, 1_000)

        self.assertEqual(cues[0].text, "hello, world")

    def test_groups_mixed_language_wraps_lines_and_attaches_punctuation(self) -> None:
        words = (
            MappedWord("w1", "你好", 0, 200, "clip:0"),
            MappedWord("w2", "MiniCut", 220, 400, "clip:0"),
            MappedWord("w3", "works", 420, 600, "clip:0"),
            MappedWord("w4", "。", 600, 650, "clip:0"),
            MappedWord("w5", "下一句", 800, 1_050, "clip:0"),
        )

        cues = build_readable_cues(
            words,
            2_000,
            SubtitleLayoutPolicy(
                max_characters_per_line=10,
                max_lines=2,
                min_duration_ms=500,
                max_duration_ms=3_000,
            ),
        )

        self.assertEqual(len(cues), 2)
        self.assertEqual(cues[0].text, "你好MiniCut\nworks。")
        self.assertEqual(cues[1].text, "下一句")
        self.assertEqual((cues[0].start_ms, cues[0].end_ms), (0, 650))

    def test_breaks_on_clip_duration_and_line_capacity(self) -> None:
        cases = (
            (
                (
                    MappedWord("w1", "one", 0, 200, "clip:0"),
                    MappedWord("w2", "two", 250, 450, "clip:1"),
                ),
                SubtitleLayoutPolicy(20, 2, 100, 2_000),
            ),
            (
                (
                    MappedWord("w1", "one", 0, 200, "clip:0"),
                    MappedWord("w2", "two", 1_100, 1_300, "clip:0"),
                ),
                SubtitleLayoutPolicy(20, 2, 100, 1_000),
            ),
            (
                (
                    MappedWord("w1", "12345", 0, 200, "clip:0"),
                    MappedWord("w2", "67890", 250, 450, "clip:0"),
                ),
                SubtitleLayoutPolicy(5, 1, 100, 2_000),
            ),
        )

        for words, policy in cases:
            with self.subTest(policy=policy):
                cues = build_readable_cues(words, 2_000, policy)
                self.assertEqual(len(cues), 2)

    def test_minimum_duration_never_overlaps_or_exceeds_video(self) -> None:
        words = (
            MappedWord("w1", "短", 0, 100, "clip:0"),
            MappedWord("w2", "。", 100, 150, "clip:0"),
            MappedWord("w3", "末尾", 400, 500, "clip:0"),
        )
        policy = SubtitleLayoutPolicy(18, 2, 800, 5_000)

        cues = build_readable_cues(words, 700, policy)
        reparsed = parse_srt(render_srt(cues, 700))

        self.assertEqual(cues[0].end_ms, 400)
        self.assertEqual(cues[-1].end_ms, 700)
        self.assertEqual(reparsed, cues)
        self.assertTrue(
            all(
                left.end_ms <= right.start_ms
                for left, right in zip(cues, cues[1:], strict=False)
            )
        )

    def test_rejects_invalid_layout_policy(self) -> None:
        invalid = ((0, 2, 800, 5_000), (18, 0, 800, 5_000), (18, 2, 900, 800))
        for values in invalid:
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    SubtitleLayoutPolicy(*values)


if __name__ == "__main__":
    unittest.main()
