import unittest

from minicut.media import MediaAsset, TimeRange
from minicut.timeline import Clip, Timeline
from minicut.timeline_validation import (
    TimelineValidationCode,
    TimelineValidationError,
    inspect_timeline_structure,
    validate_timeline_structure,
)


def _asset(asset_id: str = "asset-1", duration_ms: int = 2_000) -> MediaAsset:
    return MediaAsset(asset_id, f"/{asset_id}.mov", duration_ms, (), "test")


def _clip(
    ordinal: int,
    source_range: TimeRange,
    output_range: TimeRange,
    *,
    asset_id: str = "asset-1",
) -> Clip:
    return Clip(
        f"clip:{ordinal}",
        asset_id,
        f"segment-{ordinal}",
        source_range,
        output_range,
    )


def _valid_timeline() -> Timeline:
    return Timeline(
        (
            _clip(0, TimeRange(100, 500), TimeRange(0, 400)),
            _clip(1, TimeRange(800, 1_300), TimeRange(400, 900)),
        ),
        900,
    )


class TimelineStructureValidationTest(unittest.TestCase):
    def test_accepts_valid_ranges_order_and_media_references(self) -> None:
        timeline = _valid_timeline()

        issues = inspect_timeline_structure(timeline, (_asset(),))

        self.assertEqual(issues, ())
        validate_timeline_structure(timeline, (_asset(),))

    def test_reports_each_structural_error_with_a_machine_code(self) -> None:
        valid = _valid_timeline()
        cases = (
            (
                "unknown asset",
                Timeline(
                    (
                        _clip(
                            0,
                            TimeRange(0, 400),
                            TimeRange(0, 400),
                            asset_id="missing",
                        ),
                    ),
                    400,
                ),
                TimelineValidationCode.UNKNOWN_ASSET,
            ),
            (
                "source out of range",
                Timeline(
                    (_clip(0, TimeRange(1_800, 2_100), TimeRange(0, 300)),),
                    300,
                ),
                TimelineValidationCode.SOURCE_OUT_OF_RANGE,
            ),
            (
                "source order",
                Timeline(
                    (
                        _clip(0, TimeRange(800, 1_000), TimeRange(0, 200)),
                        _clip(1, TimeRange(100, 300), TimeRange(200, 400)),
                    ),
                    400,
                ),
                TimelineValidationCode.SOURCE_ORDER,
            ),
            (
                "source overlap",
                Timeline(
                    (
                        _clip(0, TimeRange(100, 500), TimeRange(0, 400)),
                        _clip(1, TimeRange(400, 700), TimeRange(400, 700)),
                    ),
                    700,
                ),
                TimelineValidationCode.SOURCE_OVERLAP,
            ),
            (
                "output gap",
                Timeline(
                    (
                        valid.clips[0],
                        _clip(1, TimeRange(800, 1_300), TimeRange(500, 1_000)),
                    ),
                    1_000,
                ),
                TimelineValidationCode.OUTPUT_DISCONTINUITY,
            ),
            (
                "duration mismatch",
                Timeline(valid.clips, 1_000),
                TimelineValidationCode.DURATION_MISMATCH,
            ),
        )

        for name, timeline, expected_code in cases:
            with self.subTest(name=name):
                issues = inspect_timeline_structure(timeline, (_asset(),))
                self.assertIn(expected_code, {issue.code for issue in issues})
                with self.assertRaises(TimelineValidationError) as raised:
                    validate_timeline_structure(timeline, (_asset(),))
                self.assertIn(
                    expected_code,
                    {issue.code for issue in raised.exception.issues},
                )

    def test_empty_timeline_and_duplicate_clip_ids_are_hard_errors(self) -> None:
        empty = Timeline((), 0)
        duplicate = _valid_timeline()
        duplicate.clips[1].clip_id = duplicate.clips[0].clip_id

        for timeline, expected_code in (
            (empty, TimelineValidationCode.EMPTY_TIMELINE),
            (duplicate, TimelineValidationCode.DUPLICATE_CLIP_ID),
        ):
            with self.subTest(expected_code=expected_code):
                with self.assertRaises(TimelineValidationError) as raised:
                    validate_timeline_structure(timeline, (_asset(),))
                self.assertIn(
                    expected_code,
                    {issue.code for issue in raised.exception.issues},
                )


if __name__ == "__main__":
    unittest.main()
