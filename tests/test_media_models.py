import json
import unittest
from typing import cast

from minicut.media import MediaAsset, StreamInfo, StreamType, TimeRange


class TimeRangeTest(unittest.TestCase):
    def test_duration_is_derived_from_integer_milliseconds(self) -> None:
        time_range = TimeRange(start_ms=120, end_ms=450)

        self.assertEqual(time_range.duration_ms, 330)

    def test_invalid_boundaries_are_rejected(self) -> None:
        invalid_ranges = ((-1, 10), (10, 10), (20, 10))

        for start_ms, end_ms in invalid_ranges:
            with self.subTest(start_ms=start_ms, end_ms=end_ms):
                with self.assertRaises(ValueError):
                    TimeRange(start_ms=start_ms, end_ms=end_ms)


class MediaAssetTest(unittest.TestCase):
    def test_asset_round_trips_through_json(self) -> None:
        asset = MediaAsset(
            asset_id="asset-1",
            source_path="/videos/interview.mp4",
            duration_ms=12_345,
            streams=(
                StreamInfo(index=0, stream_type=StreamType.VIDEO, codec_name="h264"),
                StreamInfo(index=1, stream_type=StreamType.AUDIO, codec_name="aac"),
            ),
        )

        encoded = json.dumps(asset.to_dict())
        decoded = cast(dict[str, object], json.loads(encoded))

        self.assertEqual(MediaAsset.from_dict(decoded), asset)

    def test_empty_id_and_negative_duration_are_rejected(self) -> None:
        valid_stream = StreamInfo(
            index=0,
            stream_type=StreamType.AUDIO,
            codec_name="aac",
        )

        with self.assertRaises(ValueError):
            MediaAsset("", "audio.m4a", 1_000, (valid_stream,))
        with self.assertRaises(ValueError):
            MediaAsset("asset-1", "audio.m4a", -1, (valid_stream,))

    def test_unknown_stream_type_is_rejected(self) -> None:
        unknown_type = cast(StreamType, "subtitle")

        with self.assertRaises(ValueError):
            StreamInfo(index=0, stream_type=unknown_type, codec_name="subrip")


if __name__ == "__main__":
    unittest.main()
