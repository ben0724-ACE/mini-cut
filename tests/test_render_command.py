import unittest

from minicut.media import MediaAsset, StreamInfo, StreamType, TimeRange
from minicut.render_command import (
    RenderCommandBuilder,
    RenderEncoding,
    VideoOutputMetadata,
)
from minicut.timeline import Clip, Timeline
from minicut.timeline_validation import TimelineTrackRequirements


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


def _multi_timeline() -> Timeline:
    first = _clip(0, 100, 500)
    second = _clip(1, 800, 1_300)
    second.output_range = TimeRange(400, 900)
    return Timeline((first, second), 900)


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
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
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


class MultiClipRenderCommandTest(unittest.TestCase):
    def test_builds_video_audio_concat_graph_with_real_stream_indexes(self) -> None:
        asset = MediaAsset(
            "asset-1",
            "/media/input.mov",
            5_000,
            (
                StreamInfo(3, StreamType.AUDIO, "aac"),
                StreamInfo(2, StreamType.VIDEO, "h264"),
            ),
            "test",
        )

        command = RenderCommandBuilder().build_multi_clip(
            _multi_timeline(),
            (asset,),
            "/output/result.mp4",
            TimelineTrackRequirements(require_audio=True, require_video=True),
        )

        graph = command[command.index("-filter_complex") + 1]
        self.assertEqual(
            command[:5], ("ffmpeg", "-nostdin", "-y", "-i", asset.source_path)
        )
        self.assertEqual(
            graph,
            "[0:2]trim=start=0.100:end=0.500,setpts=PTS-STARTPTS,"
            "scale=1920:1080:force_original_aspect_ratio=decrease,"
            "pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,"
            "format=yuv420p[v0];"
            "[0:3]atrim=start=0.100:end=0.500,asetpts=PTS-STARTPTS[a0];"
            "[0:2]trim=start=0.800:end=1.300,setpts=PTS-STARTPTS,"
            "scale=1920:1080:force_original_aspect_ratio=decrease,"
            "pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,"
            "format=yuv420p[v1];"
            "[0:3]atrim=start=0.800:end=1.300,asetpts=PTS-STARTPTS[a1];"
            "[v0][a0][v1][a1]concat=n=2:v=1:a=1[outv][outa]",
        )
        self.assertEqual(
            command[-11:],
            (
                "-map",
                "[outv]",
                "-map",
                "[outa]",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "/output/result.mp4",
            ),
        )

    def test_adds_each_distinct_source_once_and_builds_audio_only_graph(self) -> None:
        timeline = _multi_timeline()
        timeline.clips[1].source_asset_id = "asset-2"
        first = MediaAsset(
            "asset-1",
            "/media/one.wav",
            5_000,
            (StreamInfo(1, StreamType.AUDIO, "pcm_s16le"),),
            "test-1",
        )
        second = MediaAsset(
            "asset-2",
            "/media/two.wav",
            5_000,
            (StreamInfo(4, StreamType.AUDIO, "pcm_s16le"),),
            "test-2",
        )

        command = RenderCommandBuilder().build_multi_clip(
            timeline,
            (first, second),
            "/output/result.m4a",
            TimelineTrackRequirements(require_audio=True),
        )

        self.assertEqual(command.count("-i"), 2)
        graph = command[command.index("-filter_complex") + 1]
        self.assertIn("[0:1]atrim=start=0.100:end=0.500", graph)
        self.assertIn("[1:4]atrim=start=0.800:end=1.300", graph)
        self.assertTrue(graph.endswith("[a0][a1]concat=n=2:v=0:a=1[outa]"))
        self.assertNotIn("[outv]", command)

    def test_normalizes_landscape_portrait_and_fractional_frame_rates(self) -> None:
        scenarios = (
            (
                VideoOutputMetadata(1920, 1080, "30000/1001"),
                "scale=1920:1080",
                "fps=30000/1001",
            ),
            (VideoOutputMetadata(1080, 1920, "25"), "scale=1080:1920", "fps=25"),
        )

        for metadata, expected_scale, expected_fps in scenarios:
            with self.subTest(metadata=metadata):
                command = RenderCommandBuilder().build_multi_clip(
                    _multi_timeline(),
                    (_asset(),),
                    "/output/result.mp4",
                    TimelineTrackRequirements(require_video=True),
                    metadata,
                )
                graph = command[command.index("-filter_complex") + 1]
                self.assertIn(expected_scale, graph)
                self.assertIn(expected_fps, graph)
                self.assertIn("setsar=1", graph)

    def test_silent_video_omits_audio_map_and_codec(self) -> None:
        silent = MediaAsset(
            "asset-1",
            "/media/silent.mov",
            5_000,
            (StreamInfo(0, StreamType.VIDEO, "hevc"),),
            "test",
        )

        command = RenderCommandBuilder().build_multi_clip(
            _multi_timeline(),
            (silent,),
            "/output/result.mp4",
            TimelineTrackRequirements(require_video=True),
            encoding=RenderEncoding(),
        )

        self.assertIn("-c:v", command)
        self.assertIn("-pix_fmt", command)
        self.assertNotIn("-c:a", command)
        self.assertNotIn("[outa]", command)

    def test_rejects_invalid_output_metadata_and_encoding(self) -> None:
        invalid_metadata = (
            (0, 1080, "30"),
            (1921, 1080, "30"),
            (1920, 1080, "0"),
            (1920, 1080, "not-a-rate"),
        )
        for width, height, frame_rate in invalid_metadata:
            with self.subTest((width, height, frame_rate)):
                with self.assertRaises(ValueError):
                    VideoOutputMetadata(width, height, frame_rate)
        with self.assertRaisesRegex(ValueError, "encoding"):
            RenderEncoding(video_codec=" ")

    def test_rejects_single_clip_and_invalid_timeline_before_building(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least two clips"):
            RenderCommandBuilder().build_multi_clip(
                Timeline((_clip(0, 0, 500),), 500),
                (_asset(),),
                "/output/result.mp4",
                TimelineTrackRequirements(require_video=True),
            )

        invalid = _multi_timeline()
        invalid.clips[1].output_range = TimeRange(500, 1_000)
        with self.assertRaisesRegex(ValueError, "blocking validation"):
            RenderCommandBuilder().build_multi_clip(
                invalid,
                (_asset(),),
                "/output/result.mp4",
                TimelineTrackRequirements(require_video=True),
            )


if __name__ == "__main__":
    unittest.main()
