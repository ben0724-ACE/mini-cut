import unittest
from unittest.mock import patch

from minicut.text_normalization import (
    ChineseScriptPolicy,
    TextNormalizationPolicy,
    WordTextMapping,
    normalize_text,
    normalize_transcript_words,
)
from minicut.transcript import Transcript, TranscriptSource, Word


class RecordingConverter:
    def __init__(self, result: str) -> None:
        self.result = result
        self.inputs: list[str] = []

    def convert(self, text: str) -> str:
        self.inputs.append(text)
        return self.result


class ReplacingConverter:
    def __init__(self) -> None:
        self.inputs: list[str] = []

    def convert(self, text: str) -> str:
        self.inputs.append(text)
        return text.replace("體", "体").replace("與", "与")


def _transcript_with_raw_words() -> Transcript:
    return Transcript(
        transcript_id="transcript-1",
        source=TranscriptSource(
            asset_id="asset-1",
            provider="mlx-whisper",
            model="small",
        ),
        language="zh",
        words=(
            Word("word-1", "  繁體\t中文  ", 100, 500, 0.98),
            Word("word-2", " ﹗ ", 600, 700, 0.96),
            Word("word-3", " \n ", 800, 900, 0.94),
        ),
    )


class TextNormalizationTest(unittest.TestCase):
    def test_whitespace_and_chinese_punctuation_variants_are_canonical(self) -> None:
        converter = RecordingConverter("你好，世界。")

        result = normalize_text(
            "  你好\t ﹐\n世界 ｡  ",
            converter=converter,
        )

        self.assertEqual(converter.inputs, ["你好，世界。"])
        self.assertEqual(result, "你好，世界。")

    def test_default_policy_converts_traditional_chinese_to_simplified(self) -> None:
        converter = RecordingConverter("繁体中文与影片")

        result = normalize_text("繁體中文與影片", converter=converter)

        self.assertEqual(result, "繁体中文与影片")
        self.assertEqual(
            TextNormalizationPolicy().chinese_script,
            ChineseScriptPolicy.SIMPLIFIED,
        )

    def test_default_opencc_converter_uses_t2s_character_mapping(self) -> None:
        self.assertEqual(normalize_text("繁體中文與影片"), "繁体中文与影片")

    def test_preserve_policy_keeps_script_and_does_not_call_converter(self) -> None:
        converter = RecordingConverter("不应使用")

        result = normalize_text(
            "  繁體\t中文  ",
            policy=TextNormalizationPolicy(chinese_script=ChineseScriptPolicy.PRESERVE),
            converter=converter,
        )

        self.assertEqual(result, "繁體中文")
        self.assertEqual(converter.inputs, [])

    def test_blank_and_punctuation_only_text_are_deterministic(self) -> None:
        converter = RecordingConverter("！")

        self.assertEqual(normalize_text(" \t\n", converter=converter), "")
        self.assertEqual(normalize_text("  ﹗  ", converter=converter), "！")
        self.assertEqual(converter.inputs, ["！"])

    def test_chinese_words_are_joined_without_artificial_spaces(self) -> None:
        result = normalize_text(
            "你 好 ， 世 界",
            policy=TextNormalizationPolicy(chinese_script=ChineseScriptPolicy.PRESERVE),
        )

        self.assertEqual(result, "你好，世界")

    def test_english_spacing_preserves_contractions_and_decimal_points(self) -> None:
        result = normalize_text(
            "  Don't  change version 3.14 , please !  ",
            policy=TextNormalizationPolicy(chinese_script=ChineseScriptPolicy.PRESERVE),
        )

        self.assertEqual(result, "Don't change version 3.14, please!")

    def test_mixed_chinese_and_latin_text_has_stable_boundaries(self) -> None:
        result = normalize_text(
            "使用Python和Whisper large-v3模型",
            policy=TextNormalizationPolicy(chinese_script=ChineseScriptPolicy.PRESERVE),
        )

        self.assertEqual(result, "使用 Python 和 Whisper large-v3 模型")


class TranscriptWordNormalizationTest(unittest.TestCase):
    def test_mapping_preserves_raw_text_order_identity_and_timestamps(self) -> None:
        transcript = _transcript_with_raw_words()
        original = transcript.to_dict()
        converter = ReplacingConverter()

        mappings = normalize_transcript_words(transcript, converter=converter)

        self.assertEqual(
            mappings,
            (
                WordTextMapping("word-1", "  繁體\t中文  ", "繁体中文"),
                WordTextMapping("word-2", " ﹗ ", "！"),
                WordTextMapping("word-3", " \n ", ""),
            ),
        )
        words_by_id = {word.word_id: word for word in transcript.words}
        for mapping in mappings:
            self.assertEqual(words_by_id[mapping.word_id].text, mapping.raw_text)
        self.assertEqual(
            tuple((word.start_ms, word.end_ms) for word in transcript.words),
            ((100, 500), (600, 700), (800, 900)),
        )
        self.assertEqual(transcript.to_dict(), original)
        self.assertEqual(converter.inputs, ["繁體中文", "！"])

    def test_default_converter_is_loaded_once_for_the_whole_transcript(self) -> None:
        converter = ReplacingConverter()

        with patch(
            "minicut.text_normalization._load_simplified_converter",
            return_value=converter,
        ) as load_converter:
            normalize_transcript_words(_transcript_with_raw_words())

        load_converter.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
