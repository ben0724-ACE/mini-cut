import unittest
from dataclasses import replace

from minicut.media import MediaAsset, StreamInfo, StreamType, TimeRange
from minicut.output_plan import OutputItem, OutputPlan, OutputRole
from minicut.output_timeline import compile_output_timeline, validate_output_timeline
from minicut.semantic_segment import SemanticSegment
from minicut.timeline import Timeline
from minicut.timeline_validation import (
    TimelineTrackRequirements,
    TimelineValidationError,
    validate_timeline_for_render,
)


class OutputTimelineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.segments = tuple(
            SemanticSegment(
                name,
                name,
                index * 1000,
                index * 1000 + 800,
                (f"u-{name}",),
                (f"w-{name}",),
            )
            for index, name in enumerate(("a", "b", "c"))
        )
        self.plan = OutputPlan(
            "video",
            "candidate",
            "C A B",
            tuple(
                OutputItem(f"instance-{name}", name, OutputRole.BODY)
                for name in ("c", "a", "b")
            ),
        )
        self.asset = MediaAsset(
            "asset",
            "/source.mp4",
            3000,
            (StreamInfo(0, StreamType.VIDEO, "h264"),),
            "existing",
        )
        self.requirements = TimelineTrackRequirements(require_video=True)

    def test_compiles_explicit_order_without_weakening_old_validator(self) -> None:
        timeline = compile_output_timeline(self.plan, self.segments, "asset")
        self.assertEqual([clip.segment_id for clip in timeline.clips], ["c", "a", "b"])
        self.assertEqual(
            [clip.clip_id for clip in timeline.clips],
            ["instance-c", "instance-a", "instance-b"],
        )
        self.assertEqual(
            [clip.output_range.start_ms for clip in timeline.clips], [0, 800, 1600]
        )
        self.assertEqual(timeline.estimated_duration_ms, 2400)
        validate_output_timeline(
            timeline,
            self.plan,
            self.segments,
            "asset",
            (self.asset,),
            self.requirements,
        )
        with self.assertRaises(TimelineValidationError):
            validate_timeline_for_render(timeline, (self.asset,), self.requirements)

    def test_rejects_unknown_refs_bounds_track_errors_and_timeline_tampering(
        self,
    ) -> None:
        with self.assertRaises(ValueError):
            compile_output_timeline(
                replace(
                    self.plan, items=(OutputItem("x", "missing", OutputRole.BODY),)
                ),
                self.segments,
                "asset",
            )
        timeline = compile_output_timeline(self.plan, self.segments, "asset")
        for assets, requirements in (
            ((), self.requirements),
            ((replace(self.asset, duration_ms=2000),), self.requirements),
            ((self.asset,), TimelineTrackRequirements(require_audio=True)),
        ):
            with self.subTest(assets=assets), self.assertRaises(ValueError):
                validate_output_timeline(
                    timeline, self.plan, self.segments, "asset", assets, requirements
                )
        first = timeline.clips[0]
        for bad in (
            Timeline(tuple(reversed(timeline.clips)), 2400),
            Timeline(
                (replace(first, output_range=TimeRange(1, 801)), *timeline.clips[1:]),
                2400,
            ),
            Timeline(
                (
                    replace(first, source_range=TimeRange(2000, 2700)),
                    *timeline.clips[1:],
                ),
                2400,
            ),
            Timeline(timeline.clips, 2401),
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_output_timeline(
                    bad,
                    self.plan,
                    self.segments,
                    "asset",
                    (self.asset,),
                    self.requirements,
                )
