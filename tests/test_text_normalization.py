import unittest

from minicut.text_normalization import (
    ChineseScriptPolicy,
    TextNormalizationPolicy,
    normalize_text,
)


class RecordingConverter:
    def __init__(self, result: str) -> None:
        self.result = result
        self.inputs: list[str] = []

    def convert(self, text: str) -> str:
        self.inputs.append(text)
        return self.result


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

        self.assertEqual(result, "繁體 中文")
        self.assertEqual(converter.inputs, [])

    def test_blank_and_punctuation_only_text_are_deterministic(self) -> None:
        converter = RecordingConverter("！")

        self.assertEqual(normalize_text(" \t\n", converter=converter), "")
        self.assertEqual(normalize_text("  ﹗  ", converter=converter), "！")
        self.assertEqual(converter.inputs, ["！"])


if __name__ == "__main__":
    unittest.main()
