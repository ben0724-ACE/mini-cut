import json
import unittest

from minicut.semantic_segment import SegmentLabel, SemanticSegment
from minicut.semantic_segmentation import mark_segment_candidates


def _segment(ordinal: int, text: str) -> SemanticSegment:
    return SemanticSegment(
        segment_id=f"segment-{ordinal}",
        text=text,
        start_ms=ordinal * 1_000,
        end_ms=ordinal * 1_000 + 800,
        utterance_ids=(f"utterance-{ordinal}",),
        word_ids=(f"word-{ordinal}",),
    )


class SegmentLabelModelTest(unittest.TestCase):
    def test_labels_round_trip_through_json(self) -> None:
        segment = _segment(1, "嗯。")
        segment.labels = (SegmentLabel.FILLER, SegmentLabel.REPETITION_CANDIDATE)

        restored = SemanticSegment.from_dict(
            json.loads(json.dumps(segment.to_dict(), ensure_ascii=False))
        )

        self.assertEqual(restored, segment)
        self.assertEqual(
            segment.to_dict()["labels"],
            ["filler", "repetition_candidate"],
        )

    def test_duplicate_labels_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "labels"):
            SemanticSegment(
                "segment-1",
                "嗯。",
                0,
                800,
                ("utterance-1",),
                ("word-1",),
                labels=(SegmentLabel.FILLER, SegmentLabel.FILLER),
            )


class SegmentCandidateRuleTest(unittest.TestCase):
    def test_conservative_rules_mark_each_candidate_kind(self) -> None:
        source = (
            _segment(0, "嗯。"),
            _segment(1, "[静音]"),
            _segment(2, "我想说——"),
            _segment(3, "核心内容。"),
            _segment(4, "核心内容！"),
        )

        marked = mark_segment_candidates(source)

        self.assertEqual(marked[0].labels, (SegmentLabel.FILLER,))
        self.assertEqual(marked[1].labels, (SegmentLabel.SILENCE,))
        self.assertEqual(marked[2].labels, (SegmentLabel.FALSE_START,))
        self.assertEqual(marked[3].labels, (SegmentLabel.CONTENT,))
        self.assertEqual(
            marked[4].labels,
            (SegmentLabel.REPETITION_CANDIDATE,),
        )
        self.assertTrue(all(segment.labels == () for segment in source))

    def test_only_explicit_silence_markers_are_marked(self) -> None:
        markers = (
            "[silence]",
            "(silence)",
            "<silence>",
            "[静音]",
            "【静音】",
            "（静音）",
        )

        for index, marker in enumerate(markers):
            with self.subTest(marker=marker):
                marked = mark_segment_candidates((_segment(index, marker),))
                self.assertEqual(marked[0].labels, (SegmentLabel.SILENCE,))

        spoken_word = mark_segment_candidates((_segment(10, "silence"),))
        self.assertEqual(spoken_word[0].labels, (SegmentLabel.CONTENT,))

    def test_ambiguous_words_are_not_treated_as_pure_fillers(self) -> None:
        marked = mark_segment_candidates(
            (_segment(0, "那个方案就是这样。"), _segment(1, "actual content"))
        )

        self.assertEqual(marked[0].labels, (SegmentLabel.CONTENT,))
        self.assertEqual(marked[1].labels, (SegmentLabel.CONTENT,))

    def test_only_adjacent_equivalent_text_is_a_repetition_candidate(self) -> None:
        adjacent = mark_segment_candidates(
            (_segment(0, "Hello, world!"), _segment(1, " hello world "))
        )
        separated = mark_segment_candidates(
            (_segment(0, "same"), _segment(1, "other"), _segment(2, "same"))
        )

        self.assertEqual(
            adjacent[1].labels,
            (SegmentLabel.REPETITION_CANDIDATE,),
        )
        self.assertEqual(separated[2].labels, (SegmentLabel.CONTENT,))

    def test_marking_is_idempotent_and_preserves_segment_identity_and_time(
        self,
    ) -> None:
        source = (_segment(0, "uh..."), _segment(1, "content"))

        first = mark_segment_candidates(source)
        second = mark_segment_candidates(first)

        self.assertEqual(second, first)
        self.assertEqual(
            tuple(
                (segment.segment_id, segment.start_ms, segment.end_ms)
                for segment in first
            ),
            (("segment-0", 0, 800), ("segment-1", 1_000, 1_800)),
        )
        self.assertEqual(
            first[0].labels,
            (SegmentLabel.FILLER, SegmentLabel.FALSE_START),
        )


if __name__ == "__main__":
    unittest.main()
