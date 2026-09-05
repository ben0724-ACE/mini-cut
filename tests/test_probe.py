import unittest

from minicut.probe import build_ffprobe_command


class FfprobeCommandTest(unittest.TestCase):
    def test_command_requests_json_format_and_stream_metadata(self) -> None:
        source_path = "/videos/interview take.mp4"

        command = build_ffprobe_command(source_path, executable="/tools/ffprobe")

        self.assertEqual(command[0], "/tools/ffprobe")
        self.assertEqual(command[command.index("-print_format") + 1], "json")
        self.assertIn("-show_format", command)
        self.assertIn("-show_streams", command)
        self.assertEqual(command[-2:], ("-i", source_path))


if __name__ == "__main__":
    unittest.main()
