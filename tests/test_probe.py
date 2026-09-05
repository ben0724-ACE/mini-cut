import json
import unittest
from collections.abc import Mapping, Sequence
from subprocess import TimeoutExpired

from minicut.errors import ProcessingError, UserInputError
from minicut.media import StreamType
from minicut.probe import (
    Command,
    ProcessResult,
    build_ffprobe_command,
    parse_ffprobe_json,
    probe_media,
)


def ffprobe_output(
    duration: str,
    streams: Sequence[Mapping[str, object]],
) -> str:
    return json.dumps({"format": {"duration": duration}, "streams": streams})


class FakeRunner:
    def __init__(
        self,
        result: ProcessResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self._result = result
        self._error = error
        self.calls: list[tuple[Command, float]] = []

    def __call__(self, command: Command, timeout_seconds: float) -> ProcessResult:
        self.calls.append((command, timeout_seconds))
        if self._error is not None:
            raise self._error
        if self._result is None:
            raise AssertionError("FakeRunner requires a result or error")
        return self._result


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


class MediaProbeTest(unittest.TestCase):
    def test_probe_executes_the_built_command_and_returns_metadata(self) -> None:
        runner = FakeRunner(
            ProcessResult(
                return_code=0,
                stdout=ffprobe_output(
                    "1.250",
                    [{"index": 0, "codec_type": "audio", "codec_name": "aac"}],
                ),
                stderr="",
            )
        )

        result = probe_media(
            "voice.m4a",
            runner=runner,
            executable="/tools/ffprobe",
            timeout_seconds=2.5,
        )

        self.assertEqual(result.duration_ms, 1_250)
        command, timeout_seconds = runner.calls[0]
        self.assertEqual(command[0], "/tools/ffprobe")
        self.assertEqual(command[-1], "voice.m4a")
        self.assertEqual(timeout_seconds, 2.5)

    def test_nonzero_exit_is_mapped_without_exposing_stderr(self) -> None:
        runner = FakeRunner(
            ProcessResult(
                return_code=1,
                stdout="",
                stderr="private/path.mp4: invalid data",
            )
        )

        with self.assertRaisesRegex(ProcessingError, "could not read") as raised:
            probe_media("private/path.mp4", runner=runner)

        self.assertNotIn("private/path.mp4", str(raised.exception))

    def test_missing_executable_is_mapped(self) -> None:
        runner = FakeRunner(error=FileNotFoundError())

        with self.assertRaisesRegex(ProcessingError, "not available"):
            probe_media("clip.mp4", runner=runner)

    def test_timeout_is_mapped(self) -> None:
        runner = FakeRunner(error=TimeoutExpired(("ffprobe",), 5.0))

        with self.assertRaisesRegex(ProcessingError, "timed out"):
            probe_media("clip.mp4", runner=runner)

    def test_malformed_metadata_is_mapped(self) -> None:
        invalid_outputs = ("not JSON", json.dumps({"streams": []}))

        for output in invalid_outputs:
            with self.subTest(output=output):
                runner = FakeRunner(ProcessResult(0, output, ""))
                with self.assertRaisesRegex(ProcessingError, "invalid metadata"):
                    probe_media("clip.mp4", runner=runner)

    def test_media_without_supported_streams_is_rejected(self) -> None:
        runner = FakeRunner(
            ProcessResult(
                0,
                ffprobe_output(
                    "1.000",
                    [{"index": 0, "codec_type": "subtitle", "codec_name": "srt"}],
                ),
                "",
            )
        )

        with self.assertRaisesRegex(UserInputError, "no supported audio or video"):
            probe_media("subtitles.mkv", runner=runner)


if __name__ == "__main__":
    unittest.main()
