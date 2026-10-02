import re
from dataclasses import replace
from pathlib import Path

import pytest

from minicut.errors import UserInputError
from minicut.output_plan import OutputItem, OutputPlan, OutputRole
from minicut.subtitle import MappedWord
from minicut.subtitle_ass import render_translated_ass
from minicut.subtitle_font import SubtitleFont
from minicut.subtitle_layout import SubtitleGeometry
from minicut.subtitle_pages import (
    SubtitlePage,
    _wrap_lines,  # pyright: ignore[reportPrivateUsage]
    translated_pages,
)


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
        (3580, 7300),
    ]
    assert [page.translation for page in pages] == [
        "如果一家AI公司发布了一款不安全的产品，",
        "那么，你知道，有很大的机会提起民事",
    ]
    assert [page.source.replace("\n", " ") for page in pages] == [
        "And if an AI company releases a product that's not safe,",
        "there is, you know, massive opportunity for both civil",
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
    assert "\\an8\\pos(320,272)" in rendered
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
    assert "\\an8\\pos(256,244)" in rendered  # Source's first row is below translation.
    assert "\\an8\\pos(256,196)" in rendered


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


@pytest.mark.parametrize("resolution", [720, 1080])
@pytest.mark.parametrize("order", ["source_first", "translation_first"])
def test_bilingual_first_rows_stay_fixed_for_all_four_line_combinations(
    resolution: int, order: str
) -> None:
    plan = OutputPlan(
        "v", "c", "T", (OutputItem("i", "s", OutputRole.BODY),), subtitle_order=order
    )
    pages = tuple(
        SubtitlePage(
            i * 2000,
            (i + 1) * 2000,
            "Same source" + ("\nsecond source row" if source_rows == 2 else ""),
            "相同译文" + ("\n第二行译文" if translated_rows == 2 else ""),
            "zh",
        )
        for i, (source_rows, translated_rows) in enumerate(
            ((1, 1), (1, 2), (2, 1), (2, 2))
        )
    )
    rendered = render_translated_ass(
        pages,
        resolution,
        resolution * 16 // 9,
        SubtitleFont("CJK", Path("/fonts/cjk.otf")),
        plan,
    )
    for phrase in ("Same source", "相同译文"):
        positions = re.findall(r"\\an8\\pos\((\d+),(\d+)\)\}" + phrase, rendered)
        assert len(positions) == 4 and len(set(positions)) == 1


@pytest.mark.parametrize("resolution", [720, 1080])
def test_portrait_keeps_short_translation_whole_and_balances_screenshot_phrases(
    resolution: int,
) -> None:
    geometry = SubtitleGeometry.for_output(resolution, resolution * 16 // 9)
    source = "Simple question on the front page of the Wall Street Journal."
    translation = "《华尔街日报》头版上的一个简单问题。"
    tokens = source.split()
    words = tuple(
        MappedWord(str(i), token, i * 400, (i + 1) * 400, "clip")
        for i, token in enumerate(tokens)
    )
    pages = translated_pages(
        source,
        translation,
        words,
        0,
        len(words) * 400,
        bilingual=True,
        translation_language="zh",
        geometry=geometry,
    )
    assert " ".join(page.source.replace("\n", " ") for page in pages) == source
    assert all(
        (page.translation or "").replace("\n", "") == translation for page in pages
    )
    assert all(
        max(page.source.count("\n"), (page.translation or "").count("\n")) <= 1
        for page in pages
    )
    assert all(page.end_ms in {word.end_ms for word in words} for page in pages)
    desire = translated_pages(
        "You can guardrail it as you desire.",
        "你可以按自己的意愿为它设置护栏。",
        (),
        0,
        4000,
        bilingual=True,
        translation_language="zh",
        geometry=geometry,
    )
    assert len(desire) == 1
    assert desire[0].translation is not None
    assert "设置" in desire[0].translation and "意愿" in desire[0].translation
    assert not desire[0].review_reasons


def test_wrapping_preserves_english_words_contractions_and_numbers() -> None:
    text = "That's a well-known product costing 3.14 dollars."
    wrapped = _wrap_lines(text, 28)
    assert " ".join(wrapped.split()) == text
    assert "That's" in wrapped and "well-known" in wrapped and "3.14" in wrapped
    assert max(map(len, wrapped.splitlines())) <= 28
    assert min(map(len, wrapped.splitlines())) > 7


@pytest.mark.parametrize(
    "phrase",
    [
        "有一种误解，认为其中存在某种后门，以某种方式与中国有关联。",
        "它们运行在所谓的挽具之中。",
        "所以我认为这些模型是有能力的模型。",
    ],
)
def test_chinese_word_boundaries_are_preserved_in_wrapping_and_pagination(
    phrase: str,
) -> None:
    wrapped = _wrap_lines(phrase, 22)
    for word in ("存在", "后门", "所谓", "模型", "能力", "有关联"):
        if word in phrase:
            assert word in wrapped
    assert wrapped.replace("\n", "") == phrase
    pages = translated_pages(
        "This is a long source sentence which needs several pages to fit the portrait width.",
        phrase,
        (),
        0,
        6000,
        bilingual=True,
        translation_language="zh",
        portrait=True,
    )
    parts = [(page.translation or "").replace("\n", "") for page in pages]
    assert all(part == phrase for part in parts) or "".join(parts) == phrase
    for word in ("存在", "后门", "所谓", "模型"):
        if word in phrase:
            assert any(word in (page.translation or "") for page in pages)


def test_source_chinese_character_tokens_do_not_force_cuts_inside_words() -> None:
    source = "我们需要检查人工智能模型存在的风险，同时保留所有原话。"
    words = tuple(
        MappedWord(str(i), character, i * 300, (i + 1) * 300, "clip")
        for i, character in enumerate(source)
    )
    pages = translated_pages(
        source,
        "We must check the risks of AI models while keeping every original word.",
        words,
        0,
        len(words) * 300,
        bilingual=True,
        translation_language="en",
        portrait=True,
    )
    assert "".join(page.source.replace("\n", "") for page in pages) == source
    for word in ("人工智能", "模型", "存在"):
        assert any(word in page.source for page in pages)


def test_long_fast_subtitles_preserve_every_character_and_flag_review() -> None:
    source = "A very long sentence spoken much too quickly for comfortable reading."
    translation = (
        "这是一个非常长的句子，需要保留所有文字，同时明确提示人工复核阅读速度。"
    )
    pages = translated_pages(
        source,
        translation,
        (),
        0,
        600,
        bilingual=True,
        translation_language="zh",
        portrait=True,
    )
    assert len(pages) == 1
    assert " ".join(pages[0].source.split()) == source
    assert (pages[0].translation or "").replace("\n", "") == translation
    assert any("两行" in reason for reason in pages[0].review_reasons)
    assert any("0.8 秒" in reason for reason in pages[0].review_reasons)


def test_indivisible_long_word_is_retained_and_reported_for_review() -> None:
    text = "Supercalifragilisticexpialidocious"
    pages = translated_pages(
        text,
        "超长词",
        (),
        0,
        3000,
        bilingual=True,
        translation_language="zh",
        portrait=True,
    )
    assert pages[0].source == text
    assert any("长词" in reason for reason in pages[0].review_reasons)


def test_unaligned_long_translation_exposes_approximate_boundaries() -> None:
    pages = translated_pages(
        "This is a very long spoken sentence without any punctuation or pauses available for correspondence",
        "这是一段没有明确对应边界的很长译文需要按照阅读宽度进行分页而不能宣称实现语义对齐",
        (),
        0,
        8000,
        bilingual=True,
        translation_language="zh",
        portrait=True,
    )
    assert len(pages) > 1
    assert any("对应边界" in reason for page in pages for reason in page.review_reasons)
    assert all(page.start_ms < page.end_ms for page in pages)
    assert all(a.end_ms == b.start_ms for a, b in zip(pages, pages[1:], strict=False))
    assert pages[0].start_ms == 0 and pages[-1].end_ms == 8000


def test_extra_rows_are_reserved_once_and_impossible_layout_reports_action() -> None:
    pages = (
        SubtitlePage(0, 2000, "source", "第一行\n第二行\n第三行", "zh"),
        SubtitlePage(2000, 4000, "source", "短译文", "zh"),
    )
    rendered = render_translated_ass(
        pages, 720, 1280, SubtitleFont("CJK", Path("/fonts/cjk.otf"))
    )
    positions = re.findall(r"\\pos\((\d+),(\d+)\)\}source", rendered)
    assert len(set(positions)) == 1
    impossible = replace(pages[0], translation="\n".join(["一行"] * 30))
    with pytest.raises(UserInputError, match="字幕区域超出画布"):
        render_translated_ass(
            (impossible,), 720, 1280, SubtitleFont("CJK", Path("/fonts/cjk.otf"))
        )
