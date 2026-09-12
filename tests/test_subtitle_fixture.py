import unittest
from pathlib import Path

from minicut.subtitle import parse_srt, render_srt


class CjkSubtitleFixtureTest(unittest.TestCase):
    def test_utf8_fixture_preserves_chinese_english_and_mixed_punctuation(self) -> None:
        path = Path(__file__).parent / "fixtures/subtitles/cjk-mixed.srt"
        cues = parse_srt(path.read_text(encoding="utf-8"))

        self.assertEqual(len(cues), 4)
        self.assertEqual(cues[0].text, "这是中文：你好，世界！")
        self.assertEqual(cues[1].text, "This is my third sentence.")
        self.assertEqual(cues[2].text, "播客 Podcast 精选：AI 与人类。")
        self.assertIn("\n", cues[3].text)
        self.assertEqual(parse_srt(render_srt(cues, 4_000)), cues)
