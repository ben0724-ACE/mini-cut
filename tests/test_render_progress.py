import unittest

from minicut.render_progress import (
    FfmpegProgressState,
    parse_ffmpeg_progress,
)


class FfmpegProgressParserTest(unittest.TestCase):
    def test_parses_multiple_reports_and_normalizes_microseconds(self) -> None:
        events = parse_ffmpeg_progress(
            (
                "frame=12\n",
                "fps=24.5\n",
                "out_time_us=1500000\n",
                "speed=1.25x\n",
                "progress=continue\n",
                "frame=24\r\n",
                "out_time_ms=3000000\r\n",
                "progress=end\r\n",
            )
        )

        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].out_time_ms, 1_500)
        self.assertEqual(events[0].frame, 12)
        self.assertEqual(events[0].fps, 24.5)
        self.assertEqual(events[0].speed, 1.25)
        self.assertEqual(events[0].state, FfmpegProgressState.CONTINUE)
        self.assertEqual(events[1].out_time_ms, 3_000)
        self.assertEqual(events[1].state, FfmpegProgressState.END)

    def test_falls_back_to_clock_and_ignores_malformed_optional_values(self) -> None:
        events = parse_ffmpeg_progress(
            (
                "not a progress line",
                "frame=N/A",
                "fps=unknown",
                "out_time=01:02:03.456",
                "speed=N/A",
                "progress=continue",
            )
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].out_time_ms, 3_723_456)
        self.assertIsNone(events[0].frame)
        self.assertIsNone(events[0].fps)
        self.assertIsNone(events[0].speed)

    def test_completion_is_clamped_and_end_is_complete(self) -> None:
        events = parse_ffmpeg_progress(
            (
                "out_time_us=2500000",
                "progress=continue",
                "out_time_us=9999999",
                "progress=end",
            )
        )

        self.assertEqual(events[0].completion(5_000), 0.5)
        self.assertEqual(events[1].completion(5_000), 1.0)
        with self.assertRaisesRegex(ValueError, "positive"):
            events[0].completion(0)


if __name__ == "__main__":
    unittest.main()
