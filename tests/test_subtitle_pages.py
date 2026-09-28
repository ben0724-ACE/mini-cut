from pathlib import Path

from minicut.subtitle import MappedWord
from minicut.subtitle_ass import render_translated_ass
from minicut.subtitle_font import SubtitleFont
from minicut.subtitle_pages import translated_pages


def test_existing_long_bilingual_sentence_uses_speech_and_clause_boundaries() -> None:
    tokens = (
        ("And if", 0, 340), ("an", 340, 480), ("AI", 480, 820),
        ("company", 820, 1800), ("releases", 1800, 2240),
        ("a", 2240, 2420), ("product", 2420, 2700),
        ("that's", 2700, 2960), ("not", 2960, 3120),
        ("safe,", 3120, 3580), ("there", 4240, 4420),
        ("is,", 4420, 5080), ("you", 5140, 5380),
        ("know,", 5380, 5440), ("massive", 5640, 6120),
        ("opportunity", 6120, 6640), ("for", 6640, 6860),
        ("both", 6860, 7040), ("civil", 7040, 7300),
    )
    words = tuple(
        MappedWord(str(index), text, start, end, "clip")
        for index, (text, start, end) in enumerate(tokens)
    )
    source = " ".join(word.text for word in words)
    translated = "如果一家AI公司发布了一款不安全的产品，那么，你知道，有很大的机会提起民事"
    pages = translated_pages(
        source, translated, words, 0, 7300,
        bilingual=True, translation_language="zh",
    )
    assert [(page.start_ms, page.end_ms) for page in pages] == [
        (0, 3580), (3580, 5440), (5440, 7300)
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
        "Hello, world.", "你好，世界。", (), 0, 2000,
        bilingual=True, translation_language="zh",
    )
    rendered = render_translated_ass(
        pages, 640, 360, SubtitleFont("Noto Sans CJK SC", Path("/fonts/cjk.otf"))
    )
    assert "PlayResX: 640\nPlayResY: 360" in rendered
    assert "Dialogue: 0,0:00:00.00,0:00:02.00,SourceSmall" in rendered
    assert "Dialogue: 0,0:00:00.00,0:00:02.00,TranslationLarge" in rendered
    assert "\\pos(320,322)" in rendered
    assert "你好，世界。" in rendered
