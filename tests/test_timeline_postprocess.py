import unittest

from minicut.media import TimeRange
from minicut.timeline import Clip, Timeline
from minicut.timeline_postprocess import (
    TimelineAdjustmentReason,
    handle_short_isolated_clips,
    merge_nearby_clips,
)


def _clip(
    ordinal: int,
    start_ms: int,
    end_ms: int,
    *,
    asset_id: str = "asset-1",
) -> Clip:
    duration_ms = end_ms - start_ms
    return Clip(
        f"clip:{ordinal}",
        asset_id,
        f"segment-{ordinal}",
        TimeRange(start_ms, end_ms),
        TimeRange(ordinal * 1_000, ordinal * 1_000 + duration_ms),
    )


class MergeNearbyClipsTest(unittest.TestCase):
    def test_merges_below_threshold_and_preserves_all_segment_coverage(self) -> None:
        timeline = Timeline(
            (
                _clip(0, 100, 500),
                _clip(1, 550, 900),
                _clip(2, 1_500, 1_900),
            ),
            1_150,
        )

        result = merge_nearby_clips(timeline, max_gap_ms=100)

        self.assertEqual(len(result.timeline.clips), 2)
        merged = result.timeline.clips[0]
        self.assertEqual(merged.source_range, TimeRange(100, 900))
        self.assertEqual(merged.segment_ids, ("segment-0", "segment-1"))
        self.assertEqual(result.timeline.clips[1].segment_ids, ("segment-2",))
        self.assertEqual(
            tuple(clip.output_range for clip in result.timeline.clips),
            (TimeRange(0, 800), TimeRange(800, 1_200)),
        )
        self.assertEqual(result.timeline.estimated_duration_ms, 1_200)
        self.assertEqual(len(result.adjustments), 1)
        self.assertEqual(
            result.adjustments[0].reason,
            TimelineAdjustmentReason.NEARBY_MERGE,
        )
        self.assertEqual(result.adjustments[0].input_clip_ids, ("clip:0", "clip:1"))

    def test_does_not_merge_equal_threshold_or_different_assets(self) -> None:
        cases = (
            (
                "equal threshold",
                (_clip(0, 0, 400), _clip(1, 500, 900)),
                100,
            ),
            (
                "different assets",
                (
                    _clip(0, 0, 400),
                    _clip(1, 450, 900, asset_id="asset-2"),
                ),
                100,
            ),
        )

        for name, clips, threshold in cases:
            with self.subTest(name=name):
                result = merge_nearby_clips(
                    Timeline(
                        clips, sum(clip.source_range.duration_ms for clip in clips)
                    ),
                    threshold,
                )

                self.assertEqual(len(result.timeline.clips), 2)
                self.assertEqual(result.adjustments, ())

    def test_rejects_negative_threshold_or_overlapping_input(self) -> None:
        timeline = Timeline(
            (_clip(0, 0, 500), _clip(1, 400, 800)),
            900,
        )

        with self.assertRaisesRegex(ValueError, "threshold"):
            merge_nearby_clips(timeline, -1)
        with self.assertRaisesRegex(ValueError, "overlap"):
            merge_nearby_clips(timeline, 100)


class ShortIsolatedClipTest(unittest.TestCase):
    def test_removes_only_unprotected_clips_below_threshold(self) -> None:
        timeline = Timeline(
            (
                _clip(0, 0, 500),
                _clip(1, 1_000, 1_120),
                _clip(2, 2_000, 2_400),
            ),
            1_020,
        )

        result = handle_short_isolated_clips(timeline, min_duration_ms=200)

        self.assertEqual(
            tuple(clip.clip_id for clip in result.timeline.clips),
            ("clip:0", "clip:2"),
        )
        self.assertEqual(
            tuple(clip.output_range for clip in result.timeline.clips),
            (TimeRange(0, 500), TimeRange(500, 900)),
        )
        self.assertEqual(result.timeline.estimated_duration_ms, 900)
        self.assertEqual(len(result.adjustments), 1)
        self.assertEqual(
            result.adjustments[0].reason,
            TimelineAdjustmentReason.SHORT_CLIP_REMOVAL,
        )
        self.assertEqual(result.adjustments[0].input_clip_ids, ("clip:1",))
        self.assertIsNone(result.adjustments[0].output_clip_id)

    def test_preserves_short_clip_containing_any_protected_segment(self) -> None:
        merged_short = Clip(
            "clip:0",
            "asset-1",
            "segment-0",
            TimeRange(0, 120),
            TimeRange(0, 120),
            ("segment-0", "segment-protected"),
        )
        timeline = Timeline((merged_short, _clip(1, 1_000, 1_500)), 620)

        result = handle_short_isolated_clips(
            timeline,
            min_duration_ms=200,
            protected_segment_ids=("segment-protected",),
        )

        self.assertEqual(result.timeline.clips, timeline.clips)
        self.assertEqual(result.adjustments, ())

    def test_preserves_equal_threshold_and_prevents_empty_timeline(self) -> None:
        cases = (
            ("equal threshold", (_clip(0, 0, 200), _clip(1, 500, 900))),
            ("only clip", (_clip(0, 0, 100),)),
        )

        for name, clips in cases:
            with self.subTest(name=name):
                timeline = Timeline(
                    clips, sum(clip.source_range.duration_ms for clip in clips)
                )
                result = handle_short_isolated_clips(timeline, 200)

                self.assertGreaterEqual(len(result.timeline.clips), 1)
                self.assertEqual(result.adjustments, ())

    def test_rejects_invalid_threshold_or_missing_protected_content(self) -> None:
        timeline = Timeline((_clip(0, 0, 500),), 500)

        with self.assertRaisesRegex(ValueError, "minimum"):
            handle_short_isolated_clips(timeline, 0)
        with self.assertRaisesRegex(ValueError, "protected"):
            handle_short_isolated_clips(
                timeline, 200, protected_segment_ids=("missing",)
            )


if __name__ == "__main__":
    unittest.main()
