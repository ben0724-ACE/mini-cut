import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

from minicut.errors import UserInputError
from minicut.media import (
    MediaAsset,
    StreamInfo,
    StreamType,
    TimeRange,
    classify_media,
    fingerprint_media,
)


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
            content_fingerprint="sha256:example",
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
            MediaAsset("", "audio.m4a", 1_000, (valid_stream,), "sha256:example")
        with self.assertRaises(ValueError):
            MediaAsset(
                "asset-1",
                "audio.m4a",
                -1,
                (valid_stream,),
                "sha256:example",
            )

    def test_unknown_stream_type_is_rejected(self) -> None:
        unknown_type = cast(StreamType, "subtitle")

        with self.assertRaises(ValueError):
            StreamInfo(index=0, stream_type=unknown_type, codec_name="subrip")


class MediaTypeTest(unittest.TestCase):
    def test_supported_video_and_audio_are_classified(self) -> None:
        self.assertEqual(
            classify_media("recording.MP4", "video/mp4"),
            StreamType.VIDEO,
        )
        self.assertEqual(
            classify_media("voice.m4a", "audio/mp4"),
            StreamType.AUDIO,
        )

    def test_unsupported_extension_is_rejected(self) -> None:
        with self.assertRaisesRegex(UserInputError, "Unsupported media extension"):
            classify_media("notes.txt", "text/plain")

    def test_mime_type_must_match_the_extension_category(self) -> None:
        with self.assertRaisesRegex(UserInputError, "MIME type"):
            classify_media("recording.mp4", "audio/mpeg")


class MediaFingerprintTest(unittest.TestCase):
    def test_fingerprint_tracks_file_content_instead_of_path(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            original = root / "original.mp4"
            copied = root / "renamed-copy.mp4"
            modified = root / "modified.mp4"
            original.write_bytes(b"same media bytes")
            copied.write_bytes(b"same media bytes")
            modified.write_bytes(b"same media byte!")

            self.assertEqual(fingerprint_media(original), fingerprint_media(copied))
            self.assertNotEqual(
                fingerprint_media(original),
                fingerprint_media(modified),
            )


if __name__ == "__main__":
    unittest.main()
