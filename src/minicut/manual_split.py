"""Align user-inserted line breaks to existing ASR word boundaries."""

import unicodedata
from dataclasses import replace

from minicut.errors import UserInputError
from minicut.output_plan import OutputItem
from minicut.semantic_segment import SemanticSegment
from minicut.text_normalization import normalize_text
from minicut.transcript import Transcript


def alignment_text(text: str) -> str:
    return "".join(
        c
        for c in unicodedata.normalize("NFKC", normalize_text(text))
        if not c.isspace() and not unicodedata.category(c).startswith("P")
    )


def split_item_by_lines(
    item: OutputItem,
    segment: SemanticSegment,
    transcript: Transcript,
    lines: list[str],
    revision: int,
) -> tuple[OutputItem, ...]:
    if item.deleted:
        raise UserInputError("请先恢复片段后再分句")
    lines = [line.strip() for line in lines if line.strip()]
    normalized = [alignment_text(line) for line in lines]
    if len(lines) < 2 or any(not line for line in normalized):
        raise UserInputError("请至少分成两行，每行包含一句原话")
    start = segment.start_ms if item.source_start_ms is None else item.source_start_ms
    end = segment.end_ms if item.source_end_ms is None else item.source_end_ms
    words = [
        w
        for w in transcript.words
        if w.start_ms < end and w.end_ms > start and alignment_text(w.text)
    ]
    if "".join(normalized) != "".join(alignment_text(w.text) for w in words):
        raise UserInputError(
            "文字与原转录不一致，无法可靠匹配时间；请使用转录原文，仅添加换行或标点，分句后再校正文字"
        )
    offsets: dict[int, int] = {}
    consumed = 0
    for word in words:
        offsets[consumed] = word.start_ms
        consumed += len(alignment_text(word.text))
    cuts = [start]
    offset = 0
    for line in normalized[:-1]:
        offset += len(line)
        if offset not in offsets:
            raise UserInputError(
                "换行位于一个转录词内部，没有独立时间戳；请把换行移到相邻词边界"
            )
        point = offsets[offset]
        if not cuts[-1] < point < end:
            raise UserInputError("该分句处时间戳重叠或无有效时长，请调整换行位置")
        cuts.append(point)
    cuts.append(end)
    return tuple(
        replace(
            item,
            instance_id=f"{item.instance_id}-line-v{revision}-{i}",
            source_start_ms=cuts[i],
            source_end_ms=cuts[i + 1],
            display_text=line,
        )
        for i, line in enumerate(lines)
    )
