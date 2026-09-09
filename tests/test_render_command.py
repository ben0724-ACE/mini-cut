import unittest

from minicut.media import MediaAsset, StreamInfo, StreamType, TimeRange
from minicut.render_command import RenderCommandBuilder
from minicut.timeline import Clip, Timeline


def _asset(asset_id: str = "asset-1") -> MediaAsset:
    return MediaAsset(
        asset_id,
        "/media/input.mov",
        5_000,
        (
            StreamInfo(0, StreamType.VIDEO, "h264"),
            StreamInfo(1, StreamType.AUDIO, "aac"),
        ),
        "test",
    )


def _clip(ordinal: int, start_ms: int, end_ms: int) -> Clip:
    duration_ms = end_ms - start_ms
    return Clip(
        f"clip:{ordinal}",
        "asset-1",
        f"segment-{ordinal}",
        TimeRange(start_ms, end_ms),
        TimeRange(0, duration_ms),
    )


class SingleClipRenderCommandTest(unittest.TestCase):
    def test_builds_exact_seek_and_duration_as_argv(self) -> None:
        timeline = Timeline((_clip(0, 1_234, 3_579),), 2_345)

        command = RenderCommandBuilder().build_single_clip(
            timeline,
            (_asset(),),
            "/output/result.mp4",
        )

        self.assertEqual(
            command,
            (
                "ffmpeg",
                "-nostdin",
                "-y",
                "-ss",
                "1.234",
                "-i",
                "/media/input.mov",
                "-t",
                "2.345",
                "/output/result.mp4",
            ),
        )
        self.assertIsInstance(command, tuple)

    def test_rejects_non_single_timeline_and_unknown_asset(self) -> None:
        cases = (
            (Timeline((), 0), (_asset(),), "exactly one clip"),
            (
                Timeline((_clip(0, 0, 500), _clip(1, 700, 1_000)), 800),
                (_asset(),),
                "exactly one clip",
            ),
            (
                Timeline((_clip(0, 0, 500),), 500),
                (_asset("other"),),
                "known media asset",
            ),
        )

        for timeline, assets, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    RenderCommandBuilder().build_single_clip(
                        timeline,
                        assets,
                        "/output/result.mp4",
                    )


if __name__ == "__main__":
    unittest.main()
