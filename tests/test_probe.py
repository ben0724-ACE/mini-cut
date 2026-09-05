import json
import unittest
from collections.abc import Mapping, Sequence

from minicut.media import StreamType
from minicut.probe import build_ffprobe_command, parse_ffprobe_json


def ffprobe_output(
    duration: str,
    streams: Sequence[Mapping[str, object]],
) -> str:
    return json.dumps({"format": {"duration": duration}, "streams": streams})


class FfprobeCommandTest(unittest.TestCase):
    def test_command_requests_json_format_and_stream_metadata(self) -> None:
        source_path = "/videos/interview take.mp4"

        command = build_ffprobe_command(source_path, executable="/tools/ffprobe")

        self.assertEqual(command[0], "/tools/ffprobe")
        self.assertEqual(command[command.index("-print_format") + 1], "json")
        self.assertIn("-show_format", command)
        self.assertIn("-show_streams", command)
        self.assertEqual(command[-2:], ("-i", source_path))


class FfprobeJsonTest(unittest.TestCase):
    def test_audio_and_video_streams_are_mapped(self) -> None:
        output = ffprobe_output(
            "12.345",
            [
                {"index": 0, "codec_type": "video", "codec_name": "h264"},
                {"index": 1, "codec_type": "audio", "codec_name": "aac"},
            ],
        )

        result = parse_ffprobe_json(output)

        self.assertEqual(result.duration_ms, 12_345)
        self.assertEqual(
            tuple(stream.stream_type for stream in result.streams),
            (StreamType.VIDEO, StreamType.AUDIO),
        )

    def test_audio_file_and_multiple_audio_tracks_are_preserved(self) -> None:
        scenarios = (
            ([{"index": 0, "codec_type": "audio", "codec_name": "flac"}], (0,)),
            (
                [
                    {"index": 0, "codec_type": "video", "codec_name": "h264"},
                    {"index": 1, "codec_type": "audio", "codec_name": "aac"},
                    {"index": 2, "codec_type": "audio", "codec_name": "aac"},
                ],
                (1, 2),
            ),
        )

        for streams, expected_audio_indexes in scenarios:
            with self.subTest(expected_audio_indexes=expected_audio_indexes):
                result = parse_ffprobe_json(ffprobe_output("1.000", streams))
                audio_indexes = tuple(
                    stream.index
                    for stream in result.streams
                    if stream.stream_type is StreamType.AUDIO
                )
                self.assertEqual(audio_indexes, expected_audio_indexes)

    def test_video_without_an_audio_track_is_preserved(self) -> None:
        output = ffprobe_output(
            "2.500",
            [{"index": 0, "codec_type": "video", "codec_name": "hevc"}],
        )

        result = parse_ffprobe_json(output)

        self.assertEqual(len(result.streams), 1)
        self.assertEqual(result.streams[0].stream_type, StreamType.VIDEO)


if __name__ == "__main__":
    unittest.main()
