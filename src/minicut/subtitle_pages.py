"""Readable, time-aligned pages for translated output subtitles."""

import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from math import ceil

from minicut.subtitle import MappedWord
from minicut.subtitle_layout import SubtitleGeometry
from minicut.subtitle_segmentation import chinese_word_edges, is_chinese
from minicut.text_normalization import normalize_text

_STOP = "。！？.!?"
_PAUSE = "，,；;：:、"
_CLOSING = _STOP + _PAUSE + "）】》」』”’)]}"
_OPENING = "（【《「『“‘([{"


@dataclass(frozen=True, slots=True)
class SubtitlePage:
    start_ms: int
    end_ms: int
    source: str
    translation: str | None = None
    translation_language: str | None = None
    review_reasons: tuple[str, ...] = ()

    @property
    def text(self) -> str:
        return "\n".join(part for part in (self.source, self.translation) if part)


def _cells(text: str) -> int:
    return sum(
        2 if unicodedata.east_asian_width(character) in "WF" else 1
        for character in text
    )


def _safe_break(text: str, index: int) -> bool:
    if index <= 0 or index >= len(text):
        return False
    before, after = text[index - 1], text[index]
    if after in _CLOSING or before in _OPENING:
        return False
    if (
        is_chinese(before)
        and is_chinese(after)
        and index not in chinese_word_edges(text)
    ):
        return False
    # Keep contractions, hyphenated words, and decimal numbers intact.
    for offset in (index - 1, index):
        if (
            0 < offset < len(text) - 1
            and text[offset] in "'’-."
            and (
                text[offset - 1].isascii()
                and text[offset - 1].isalnum()
                and text[offset + 1].isascii()
                and text[offset + 1].isalnum()
            )
        ):
            return False
    return not (
        before.isascii() and before.isalnum() and after.isascii() and after.isalnum()
    )


def _boundary_bonus(text: str, index: int) -> float:
    before = text[index - 1]
    if before in _STOP:
        return 0.30
    if before in _PAUSE:
        return 0.25
    if text[index:].startswith(("关于", "那么", "然后", "但是", "因此", "其中")):
        return 0.15
    if text[index:].startswith(("为", "与", "把", "在", "按", "向", "对")):
        return 0.24
    if before.isspace():
        return 0.04
    return 0.0


def _break_penalty(text: str, index: int) -> float:
    """Local readability hints, without claiming Chinese word segmentation."""
    if text[index] in "的了着过" or text[index - 1] in "不没第":
        return 0.35
    if text[index - 1].isdigit() and text[index] in "年月日秒分个万亿%％":
        return 0.35
    # Prefer keeping a short quoted/book title together when possible.
    for opening, closing in (("《", "》"), ("“", "”"), ("「", "」")):
        left = text.rfind(opening, 0, index)
        right = text.find(closing, index)
        if left >= 0 and right >= 0 and closing not in text[left:index]:
            return 0.3
    return 0.0


def _partition_text(
    text: str,
    count: int,
    targets: tuple[float, ...] | None = None,
    *,
    stable_limit: int = 0,
    preferred_edges: tuple[int | None, ...] | None = None,
    limit: float | None = None,
    measure: Callable[[str], float] = _cells,
) -> tuple[str, ...]:
    """Keep punctuation attached and prefer clause endings over equal character cuts."""
    cleaned = " ".join(text.split())
    if count == 1:
        return (cleaned,)
    if len(cleaned) < count * 4:
        return (cleaned,) * count
    if (
        stable_limit
        and _cells(cleaned) <= stable_limit
        and not any(character in _STOP + _PAUSE for character in cleaned[:-1])
    ):
        # An unpunctuated short phrase reads better held across source pages.
        return (cleaned,) * count
    total = _cells(cleaned)
    edges = [0]
    for page in range(1, count):
        remaining = count - page
        target = targets[page - 1] if targets is not None else page / count
        preferred = preferred_edges[page - 1] if preferred_edges is not None else None
        choices = tuple(
            index
            for index in range(edges[-1] + 4, len(cleaned) - remaining * 4 + 1)
            if _safe_break(cleaned, index)
        )
        if limit is not None:
            fitting = tuple(
                index
                for index in choices
                if (
                    measure(cleaned[edges[-1] : index].strip()) <= limit * 2
                    and measure(cleaned[index:].strip()) <= remaining * limit * 2
                )
            )
            if fitting:
                choices = fitting
        best = (
            preferred
            if preferred in choices
            else min(
                choices,
                key=lambda index: (
                    abs(_cells(cleaned[:index]) / total - target)
                    - _boundary_bonus(cleaned, index)
                    + _break_penalty(cleaned, index),
                    abs(_cells(cleaned[edges[-1] : index]) - total / count),
                ),
                default=None,
            )
        )
        if best is None:
            return (cleaned,) * count
        edges.append(best)
    edges.append(len(cleaned))
    return tuple(cleaned[a:b].strip() for a, b in zip(edges, edges[1:], strict=False))


def _wrap_lines(
    text: str,
    limit: float,
    measure: Callable[[str], float] = _cells,
) -> str:
    if measure(text) <= limit:
        return text
    # Balanced two-line layouts avoid leaving a single word/character on line two.
    choices = [
        index
        for index in range(1, len(text))
        if _safe_break(text, index)
        and measure(text[:index].strip()) <= limit
        and measure(text[index:].strip()) <= limit
    ]
    if choices:
        best = min(
            choices,
            key=lambda index: (
                abs(measure(text[:index].strip()) - measure(text[index:].strip()))
                / limit
                - _boundary_bonus(text, index)
                + _break_penalty(text, index)
            ),
        )
        return text[:best].strip() + "\n" + text[best:].strip()
    # An indivisible over-wide token is retained for review, never cut or hidden.
    candidates = [
        index
        for index in range(1, len(text))
        if _safe_break(text, index) and measure(text[:index].strip()) <= limit
    ]
    if not candidates:
        return text
    best = min(
        candidates,
        key=lambda index: (
            abs(measure(text[:index].strip()) - limit) / limit
            - _boundary_bonus(text, index) / 2
            + _break_penalty(text, index)
        ),
    )
    return text[:best].strip() + "\n" + _wrap_lines(text[best:].strip(), limit, measure)


def _word_groups(
    words: tuple[MappedWord, ...],
    count: int,
    limit: float = 43,
    measure: Callable[[str], float] = _cells,
) -> tuple[tuple[MappedWord, ...], ...]:
    if count == 1:
        return (words,)
    start, end = words[0].start_ms, words[-1].end_ms
    duration = max(1, end - start)
    total = sum(_cells(word.text) + 1 for word in words)
    text = normalize_text(" ".join(word.text for word in words))
    allowed = tuple(
        index
        for index in range(1, len(words))
        if not any(is_chinese(character) for character in text)
        or _safe_break(
            text, len(normalize_text(" ".join(word.text for word in words[:index])))
        )
    )
    count = min(count, len(allowed) + 1)
    boundaries = [0]
    for page in range(1, count):
        remaining = count - page
        choices = tuple(
            index
            for index in allowed
            if index > boundaries[-1]
            and sum(edge > index for edge in allowed) >= remaining - 1
        )

        def score(
            index: int, target: float = page / count, remaining_pages: int = remaining
        ) -> float:
            current = words[index - 1]
            time_ratio = (current.end_ms - start) / duration
            text_ratio = sum(_cells(word.text) + 1 for word in words[:index]) / total
            pause_ms = words[index].start_ms - current.end_ms
            bonus = (
                _boundary_bonus(current.text, len(current.text)) if current.text else 0
            )
            if pause_ms >= 180:
                bonus += 0.12
            part = normalize_text(
                " ".join(w.text for w in words[boundaries[-1] : index])
            )
            rest = normalize_text(" ".join(w.text for w in words[index:]))
            overflow = max(0, measure(part) / limit - 2) + max(
                0, measure(rest) / (limit * remaining_pages) - 2
            )
            return (
                abs(time_ratio - target)
                + abs(text_ratio - target)
                - bonus
                + overflow * 2
            )

        boundaries.append(min(choices, key=score))
    boundaries.append(len(words))
    return tuple(words[a:b] for a, b in zip(boundaries, boundaries[1:], strict=False))


def translated_pages(
    source: str,
    translation: str,
    words: tuple[MappedWord, ...],
    start_ms: int,
    end_ms: int,
    *,
    bilingual: bool,
    translation_language: str,
    portrait: bool = False,
    source_scale: float = 1.0,
    translation_scale: float = 1.0,
    horizontal_percent: int = 50,
    geometry: SubtitleGeometry | None = None,
) -> tuple[SubtitlePage, ...]:
    """Page saved text without changing either language or the source media."""
    available_width = min(horizontal_percent, 100 - horizontal_percent) / 50
    source_limit = max(
        8, round((26 if portrait else 43) * available_width / source_scale)
    )
    translation_limit = max(
        8, round((22 if portrait else 46) * available_width / translation_scale)
    )
    source_measure: Callable[[str], float] = _cells
    translation_measure: Callable[[str], float] = _cells
    if geometry is not None:
        source_size, translation_size = geometry.sizes(translation_language)
        source_measure = geometry.measure(source_size)
        translation_measure = geometry.measure(translation_size, translated=True)
        source_limit = translation_limit = geometry.available_width
    source = " ".join(source.split())
    translation = " ".join(translation.split())
    desired = max(
        ceil(len(_wrap_lines(source, source_limit, source_measure).splitlines()) / 2)
        if bilingual
        else 1,
        ceil(
            len(
                _wrap_lines(
                    translation, translation_limit, translation_measure
                ).splitlines()
            )
            / 2
        ),
    )
    duration = end_ms - start_ms
    maximum = max(1, duration // 1_100)
    if words and bilingual:
        maximum = min(maximum, len(words))
    best_pages: tuple[SubtitlePage, ...] = ()
    best_overflow = float("inf")
    for count in range(min(max(1, desired), maximum), maximum + 1):
        pages = _pages_for_count(
            source,
            translation,
            words,
            start_ms,
            end_ms,
            bilingual,
            translation_language,
            count,
            source_limit,
            translation_limit,
            source_measure,
            translation_measure,
        )
        overflow = sum(
            max(0, text.count("\n") - 1)
            for page in pages
            for text in (page.source, page.translation or "")
        )
        if overflow < best_overflow:
            best_pages, best_overflow = pages, overflow
        if overflow == 0:
            break
    return best_pages


def _pages_for_count(
    source: str,
    translation: str,
    words: tuple[MappedWord, ...],
    start_ms: int,
    end_ms: int,
    bilingual: bool,
    translation_language: str,
    count: int,
    source_limit: float,
    translation_limit: float,
    source_measure: Callable[[str], float],
    translation_measure: Callable[[str], float],
) -> tuple[SubtitlePage, ...]:
    duration = end_ms - start_ms
    if words and bilingual and count > 1:
        groups = _word_groups(words, count, source_limit, source_measure)
        count = len(groups)
        source_parts = tuple(
            normalize_text(" ".join(w.text for w in group)) for group in groups
        )
        ends = tuple(group[-1].end_ms for group in groups[:-1]) + (end_ms,)
    else:
        source_parts = (
            _partition_text(source, count, limit=source_limit, measure=source_measure)
            if bilingual
            else ("",) * count
        )
        ends = tuple(
            start_ms + duration * page // count for page in range(1, count + 1)
        )
    if bilingual:
        total_source = sum(_cells(part) for part in source_parts)
        targets = (
            tuple(
                sum(_cells(part) for part in source_parts[:page]) / total_source
                for page in range(1, count)
            )
            if total_source
            else None
        )
    else:
        targets = None
    translated_marks = [
        index + 1
        for index, character in enumerate(translation)
        if character in _STOP + _PAUSE
    ]
    preferred_edges: tuple[int | None, ...] | None = None
    if bilingual:
        seen = 0
        preferred: list[int | None] = []
        for part in source_parts[:-1]:
            seen += sum(character in _STOP + _PAUSE for character in part)
            preferred.append(
                translated_marks[seen - 1]
                if part.strip()
                and seen <= len(translated_marks)
                and part.rstrip()[-1] in _STOP + _PAUSE
                else None
            )
        preferred_edges = tuple(preferred)
    # With no paired clause boundary, hold a complete short translation rather
    # than manufacture correspondence by splitting it in proportion to English.
    hold_translation = (
        count > 1
        and _wrap_lines(translation, translation_limit, translation_measure).count("\n")
        < 2
        and not any(preferred_edges or ())
    )
    translated_parts = (
        (translation,) * count
        if hold_translation
        else _partition_text(
            translation,
            count,
            targets,
            preferred_edges=preferred_edges,
            limit=translation_limit,
            measure=translation_measure,
        )
    )
    translated_edges: list[int] = []
    consumed = 0
    for part in translated_parts[:-1]:
        consumed = translation.find(part, consumed) + len(part)
        translated_edges.append(consumed)
    paired_edges_match = (
        preferred_edges is not None and tuple(translated_edges) == preferred_edges
    )
    approximate = (
        bool(translation)
        and count > 1
        and not hold_translation
        and (
            not words
            or not bilingual
            or not preferred_edges
            or any(edge is None for edge in preferred_edges)
            or not paired_edges_match
        )
    )
    pages: list[SubtitlePage] = []
    cursor = start_ms
    for source_part, translated_part, end in zip(
        source_parts, translated_parts, ends, strict=True
    ):
        end = min(end_ms, max(cursor + 1, end))
        source_lines = (
            _wrap_lines(source_part, source_limit, source_measure) if bilingual else ""
        )
        translation_lines = _wrap_lines(
            translated_part, translation_limit, translation_measure
        )
        reasons: list[str] = []
        if approximate:
            reasons.append("译文分页缺少可靠的原文对应边界，请对照原音人工复核。")
        if count > 1 and not (words and bilingual):
            reasons.append("字幕分页时间按文字长度估算，请对照原音人工复核。")
        if end - cursor < 800:
            reasons.append("字幕页显示不足 0.8 秒，请试听并检查阅读速度。")
        if max(source_lines.count("\n"), translation_lines.count("\n")) >= 2:
            reasons.append(
                "字幕超过建议的每种语言两行；已保留全文，请拆分句子或调整字号。"
            )
        if any(
            source_measure(line) > source_limit for line in source_lines.splitlines()
        ) or any(
            translation_measure(line) > translation_limit
            for line in translation_lines.splitlines()
        ):
            reasons.append(
                "字幕含无法在安全宽度内显示的长词，请调整文字、字号或横向位置。"
            )
        pages.append(
            SubtitlePage(
                cursor,
                end,
                source_lines,
                translation_lines,
                translation_language,
                tuple(reasons),
            )
        )
        cursor = end
    return tuple(pages)
