from pathlib import Path

from minicut.output_plan import OutputItem, OutputPlan, OutputRole
from minicut.subtitle import MappedWord
from minicut.subtitle_ass import render_translated_ass
from minicut.subtitle_font import SubtitleFont
from minicut.subtitle_pages import translated_pages


def test_existing_long_bilingual_sentence_uses_speech_and_clause_boundaries() -> None:
    tokens = (
        ("And if", 0, 340),
        ("an", 340, 480),
        ("AI", 480, 820),
        ("company", 820, 1800),
        ("releases", 1800, 2240),
        ("a", 2240, 2420),
        ("product", 2420, 2700),
        ("that's", 2700, 2960),
        ("not", 2960, 3120),
        ("safe,", 3120, 3580),
        ("there", 4240, 4420),
        ("is,", 4420, 5080),
        ("you", 5140, 5380),
        ("know,", 5380, 5440),
        ("massive", 5640, 6120),
        ("opportunity", 6120, 6640),
        ("for", 6640, 6860),
        ("both", 6860, 7040),
        ("civil", 7040, 7300),
    )
    words = tuple(
        MappedWord(str(index), text, start, end, "clip")
        for index, (text, start, end) in enumerate(tokens)
    )
    source = " ".join(word.text for word in words)
    translated = (
        "如果一家AI公司发布了一款不安全的产品，那么，你知道，有很大的机会提起民事"
    )
    pages = translated_pages(
        source,
        translated,
        words,
        0,
        7300,
        bilingual=True,
        translation_language="zh",
    )
    assert [(page.start_ms, page.end_ms) for page in pages] == [
        (0, 3580),
        (3580, 5440),
        (5440, 7300),
    ]
    assert [page.translation for page in pages] == [
        "如果一家AI公司发布了一款不安全的产品，",
        "那么，你知道，",
        "有很大的机会提起民事",
    ]
    assert [page.source.replace("\n", " ") for page in pages] == [
        "And if an AI company releases a product that's not safe,",
        "there is, you know,",
        "massive opportunity for both civil",
    ]


def test_styled_ass_separates_languages_and_places_them_above_bottom_margin() -> None:
    pages = translated_pages(
        "Hello, world.",
        "你好，世界。",
        (),
        0,
        2000,
        bilingual=True,
        translation_language="zh",
    )
    rendered = render_translated_ass(
        pages, 640, 360, SubtitleFont("Noto Sans CJK SC", Path("/fonts/cjk.otf"))
    )
    assert "PlayResX: 640\nPlayResY: 360" in rendered
    assert "Dialogue: 0,0:00:00.00,0:00:02.00,SourceSmall" in rendered
    assert "Dialogue: 0,0:00:00.00,0:00:02.00,TranslationLarge" in rendered
    assert "\\pos(320,322)" in rendered
    assert "你好，世界。" in rendered


def test_styled_ass_uses_saved_position_sizes_and_language_order() -> None:
    pages = translated_pages(
        "Hello, world.",
        "你好，世界。",
        (),
        0,
        2000,
        bilingual=True,
        translation_language="zh",
    )
    plan = OutputPlan(
        "video",
        "candidate",
        "title",
        (OutputItem("body", "s", OutputRole.BODY),),
        subtitle_source_scale=1.2,
        subtitle_translation_scale=0.8,
        subtitle_horizontal_percent=40,
        subtitle_bottom_percent=20,
        subtitle_order="translation_first",
    )
    rendered = render_translated_ass(
        pages,
        640,
        360,
        SubtitleFont("Noto Sans CJK SC", Path("/fonts/cjk.otf")),
        plan,
    )
    assert "Style: SourceSmall,Noto Sans CJK SC,18," in rendered
    assert "Style: TranslationLarge,Noto Sans CJK SC,16," in rendered
    assert "\\pos(256,288)" in rendered  # Source is below the translation.
    assert "\\pos(256,200)" not in rendered


def test_larger_offset_subtitles_use_shorter_readable_pages() -> None:
    source = "Hello wonderful world for everyone watching this video."
    translated = "你好，这个视频里有很多观众正在观看。"
    normal = translated_pages(
        source, translated, (), 0, 6000, bilingual=True, translation_language="zh"
    )
    offset = translated_pages(
        source,
        translated,
        (),
        0,
        6000,
        bilingual=True,
        translation_language="zh",
        source_scale=1.5,
        translation_scale=1.5,
        horizontal_percent=20,
    )
    assert len(offset) > len(normal)
    assert offset[0].start_ms == 0 and offset[-1].end_ms == 6000
