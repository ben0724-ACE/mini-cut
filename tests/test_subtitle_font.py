import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from minicut.errors import UserInputError
from minicut.subtitle_font import SubtitleFont, resolve_subtitle_font


class SubtitleFontTest(unittest.TestCase):
    def test_explicit_font_requires_readable_file_and_safe_family(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "中文 font.ttf"
            path.write_bytes(b"test-font")
            env = {
                "MINICUT_SUBTITLE_FONT_PATH": str(path),
                "MINICUT_SUBTITLE_FONT_NAME": "Noto Sans CJK SC",
            }
            font = resolve_subtitle_font(env)
            self.assertEqual(font, SubtitleFont("Noto Sans CJK SC", path))
            with patch("minicut.subtitle_font.os.access", return_value=False):
                with self.assertRaisesRegex(UserInputError, "readable"):
                    resolve_subtitle_font(env)
            path.unlink()
            with self.assertRaisesRegex(UserInputError, "readable"):
                resolve_subtitle_font(env)

        for name in ("", "Arial,FontSize=99", "bad\nname", "font:option"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                SubtitleFont(name, Path("/fonts/font.ttf"))

    def test_partial_configuration_is_rejected_without_silent_fallback(self) -> None:
        for env in (
            {"MINICUT_SUBTITLE_FONT_PATH": "/missing.ttf"},
            {"MINICUT_SUBTITLE_FONT_NAME": "Noto Sans CJK SC"},
        ):
            with self.subTest(env=env), self.assertRaisesRegex(UserInputError, "both"):
                resolve_subtitle_font(env)

    def test_platform_defaults_and_missing_font_have_actionable_error(self) -> None:
        for platform, family in (
            ("darwin", "Arial Unicode MS"),
            ("win32", "Microsoft YaHei"),
            ("linux", "Noto Sans CJK SC"),
        ):
            with self.subTest(platform=platform):
                with (
                    patch.object(Path, "is_file", return_value=True),
                    patch("minicut.subtitle_font.os.access", return_value=True),
                ):
                    self.assertEqual(
                        resolve_subtitle_font({}, platform=platform).family, family
                    )
                with patch.object(Path, "is_file", return_value=False):
                    with self.assertRaisesRegex(
                        UserInputError, "MINICUT_SUBTITLE_FONT_PATH"
                    ):
                        resolve_subtitle_font({}, platform=platform)
