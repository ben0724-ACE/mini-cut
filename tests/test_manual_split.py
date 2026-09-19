from dataclasses import replace

import pytest

from minicut.errors import UserInputError
from minicut.manual_split import split_item_by_lines
from minicut.output_plan import OutputItem, OutputRole
from minicut.semantic_segment import SemanticSegment
from minicut.transcript import Transcript, TranscriptSource, Word


def fixture() -> tuple[OutputItem, SemanticSegment, Transcript]:
    words = (
        Word("a", "多少", 100, 800),
        Word("b", "多少", 900, 1300),
        Word("c", "我觉得", 1600, 2100),
        Word("d", "努力比较多", 2200, 3200),
        Word("e", "是吗", 3400, 3900),
    )
    transcript = Transcript("t", TranscriptSource("asset", "test", "test"), "zh", words)
    segment = SemanticSegment(
        "s",
        "多少多少我觉得努力比较多是吗",
        100,
        3900,
        ("u",),
        tuple(w.word_id for w in words),
    )
    item = OutputItem("i", "s", OutputRole.BODY, source_start_ms=0, source_end_ms=4000)
    return item, segment, transcript


def test_dialogue_line_breaks_match_repeated_words_without_gaps() -> None:
    item, segment, transcript = fixture()
    parts = split_item_by_lines(
        item, segment, transcript, ["多少？多少？", "我觉得努力比较多。", "是吗？"], 2
    )
    assert [(p.source_start_ms, p.source_end_ms) for p in parts] == [
        (0, 1600),
        (1600, 3400),
        (3400, 4000),
    ]
    assert [p.display_text for p in parts] == [
        "多少？多少？",
        "我觉得努力比较多。",
        "是吗？",
    ]
    assert all(p.segment_id == "s" for p in parts)
    assert item.source_end_ms == 4000


@pytest.mark.parametrize(
    "lines",
    [
        ["多少", "我觉得努力比较多是吗"],
        ["多少多少我觉", "得努力比较多是吗"],
        ["多少多少我觉得努力比较多是吗"],
    ],
)
def test_unmatched_or_inside_word_split_does_not_guess_time(lines: list[str]) -> None:
    item, segment, transcript = fixture()
    with pytest.raises(UserInputError):
        split_item_by_lines(item, segment, transcript, lines, 2)
    with pytest.raises(UserInputError):
        split_item_by_lines(
            replace(item, deleted=True),
            segment,
            transcript,
            ["多少多少", "我觉得努力比较多是吗"],
            2,
        )
