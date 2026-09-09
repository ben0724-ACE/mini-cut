import random
import unittest

from minicut.media import MediaAsset, StreamInfo, StreamType, TimeRange
from minicut.timeline import Clip, Timeline
from minicut.timeline_postprocess import JumpCutRisk, TimelineRiskReason
from minicut.timeline_validation import (
    TimelineTrackRequirements,
    TimelineValidationCode,
    TimelineValidationError,
    ValidationSeverity,
    build_timeline_diagnostics,
    inspect_timeline_structure,
    inspect_timeline_tracks,
    validate_timeline_for_render,
    validate_timeline_structure,
    validate_timeline_tracks,
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


class TimelineTrackValidationTest(unittest.TestCase):
    def test_accepts_audio_only_and_multitrack_video_assets(self) -> None:
        timeline = _valid_timeline()
        audio_asset = MediaAsset(
            "asset-1",
            "/audio.wav",
            2_000,
            (StreamInfo(0, StreamType.AUDIO, "pcm_s16le"),),
            "test",
        )
        multitrack_asset = MediaAsset(
            "asset-1",
            "/video.mov",
            2_000,
            (
                StreamInfo(0, StreamType.VIDEO, "h264"),
                StreamInfo(1, StreamType.AUDIO, "aac"),
                StreamInfo(2, StreamType.AUDIO, "aac"),
            ),
            "test",
        )

        self.assertEqual(
            inspect_timeline_tracks(
                timeline,
                (audio_asset,),
                TimelineTrackRequirements(require_audio=True),
            ),
            (),
        )
        validate_timeline_tracks(
            timeline,
            (multitrack_asset,),
            TimelineTrackRequirements(require_audio=True, require_video=True),
        )

    def test_reports_missing_required_audio_or_video_track(self) -> None:
        timeline = _valid_timeline()
        cases = (
            (
                MediaAsset(
                    "asset-1",
                    "/silent.mov",
                    2_000,
                    (StreamInfo(0, StreamType.VIDEO, "h264"),),
                    "test",
                ),
                TimelineTrackRequirements(require_audio=True, require_video=True),
                TimelineValidationCode.MISSING_AUDIO_TRACK,
            ),
            (
                MediaAsset(
                    "asset-1",
                    "/audio.wav",
                    2_000,
                    (StreamInfo(0, StreamType.AUDIO, "pcm_s16le"),),
                    "test",
                ),
                TimelineTrackRequirements(require_video=True),
                TimelineValidationCode.MISSING_VIDEO_TRACK,
            ),
        )

        for asset, requirements, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                issues = inspect_timeline_tracks(timeline, (asset,), requirements)
                self.assertEqual(issues[0].code, expected_code)
                with self.assertRaises(TimelineValidationError):
                    validate_timeline_tracks(timeline, (asset,), requirements)

    def test_rejects_empty_track_requirements(self) -> None:
        with self.assertRaisesRegex(ValueError, "track"):
            TimelineTrackRequirements()

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


class TimelineRenderDiagnosticsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.requirements = TimelineTrackRequirements(require_video=True)
        self.video_asset = MediaAsset(
            "asset-1",
            "/video.mov",
            2_000,
            (StreamInfo(0, StreamType.VIDEO, "h264"),),
            "test",
        )

    def test_warning_is_reported_without_blocking_or_mutating_timeline(self) -> None:
        timeline = _valid_timeline()
        before = timeline.to_dict()
        risk = JumpCutRisk(
            TimelineRiskReason.SOURCE_GAP,
            "clip:0",
            "clip:1",
            300,
            400,
            "The cut may be visible.",
        )

        summary = validate_timeline_for_render(
            timeline,
            (self.video_asset,),
            self.requirements,
            (risk,),
        )

        self.assertTrue(summary.can_render)
        self.assertEqual(summary.error_count, 0)
        self.assertEqual(summary.warning_count, 1)
        self.assertEqual(summary.clip_count, 2)
        self.assertEqual(summary.estimated_duration_ms, 900)
        self.assertEqual(summary.issues[0].severity, ValidationSeverity.WARNING)
        self.assertEqual(timeline.to_dict(), before)

    def test_hard_errors_are_summarized_and_block_rendering(self) -> None:
        timeline = Timeline(
            (_clip(0, TimeRange(1_900, 2_100), TimeRange(0, 200)),),
            200,
        )

        summary = build_timeline_diagnostics(
            timeline,
            (self.video_asset,),
            self.requirements,
        )

        self.assertFalse(summary.can_render)
        self.assertEqual(summary.error_count, 1)
        self.assertEqual(
            summary.issues[0].code,
            TimelineValidationCode.SOURCE_OUT_OF_RANGE,
        )
        with self.assertRaises(TimelineValidationError) as raised:
            validate_timeline_for_render(
                timeline,
                (self.video_asset,),
                self.requirements,
            )
        self.assertEqual(raised.exception.issues, summary.issues)

    def test_generated_invalid_intervals_never_pass_validation(self) -> None:
        generator = random.Random(20260909)

        for index in range(100):
            source_start = generator.randint(1_700, 1_999)
            source_end = generator.randint(2_001, 2_500)
            duration_ms = source_end - source_start
            output_start = generator.randint(0, 500)
            timeline = Timeline(
                (
                    _clip(
                        index,
                        TimeRange(source_start, source_end),
                        TimeRange(output_start, output_start + duration_ms),
                    ),
                ),
                output_start + duration_ms,
            )
            with self.subTest(index=index):
                summary = build_timeline_diagnostics(
                    timeline,
                    (self.video_asset,),
                    self.requirements,
                )
                self.assertFalse(summary.can_render)
                self.assertIn(
                    TimelineValidationCode.SOURCE_OUT_OF_RANGE,
                    {issue.code for issue in summary.issues},
                )
                with self.assertRaises(TimelineValidationError):
                    validate_timeline_for_render(
                        timeline,
                        (self.video_asset,),
                        self.requirements,
                    )


if __name__ == "__main__":
    unittest.main()
