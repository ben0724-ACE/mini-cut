import json
import unittest
from collections.abc import Callable

from minicut.media import TimeRange
from minicut.timeline import (
    TIMELINE_SCHEMA_VERSION,
    Clip,
    Timeline,
)


def _clip() -> Clip:
    return Clip(
        clip_id="clip-0",
        source_asset_id="asset-1",
        segment_id="segment-2",
        source_range=TimeRange(2_000, 3_200),
        output_range=TimeRange(0, 1_200),
    )


class TimelineModelTest(unittest.TestCase):
    def test_timeline_round_trips_clip_ranges_and_version(self) -> None:
        timeline = Timeline((_clip(),), 1_200)

        restored = Timeline.from_dict(
            json.loads(json.dumps(timeline.to_dict(), ensure_ascii=False))
        )

        self.assertEqual(restored, timeline)
        self.assertEqual(restored.schema_version, TIMELINE_SCHEMA_VERSION)
        self.assertEqual(restored.clips[0].source_range, TimeRange(2_000, 3_200))
        self.assertEqual(restored.clips[0].output_range, TimeRange(0, 1_200))

    def test_clip_rejects_blank_identity_fields(self) -> None:
        invalid_factories: tuple[Callable[[], Clip], ...] = (
            lambda: Clip(
                " ",
                "asset-1",
                "segment-1",
                TimeRange(0, 100),
                TimeRange(0, 100),
            ),
            lambda: Clip(
                "clip-1",
                " ",
                "segment-1",
                TimeRange(0, 100),
                TimeRange(0, 100),
            ),
            lambda: Clip(
                "clip-1", "asset-1", " ", TimeRange(0, 100), TimeRange(0, 100)
            ),
        )

        for create_clip in invalid_factories:
            with self.subTest(create_clip=create_clip):
                with self.assertRaises(ValueError):
                    create_clip()

    def test_timeline_rejects_invalid_version_and_duration(self) -> None:
        invalid_factories: tuple[Callable[[], Timeline], ...] = (
            lambda: Timeline((_clip(),), -1),
            lambda: Timeline((_clip(),), 1_200, schema_version=2),
            lambda: Timeline((_clip(),), 1_200, schema_version=True),
        )

        for create_timeline in invalid_factories:
            with self.subTest(create_timeline=create_timeline):
                with self.assertRaises(ValueError):
                    create_timeline()


if __name__ == "__main__":
    unittest.main()
