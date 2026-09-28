"""Readable, time-aligned pages for translated output subtitles."""

import unicodedata
from dataclasses import dataclass
from math import ceil

from minicut.subtitle import MappedWord
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
    if before.isspace():
        return 0.04
    return 0.0


def _partition_text(
    text: str,
    count: int,
    targets: tuple[float, ...] | None = None,
    *,
    stable_limit: int = 0,
    preferred_edges: tuple[int | None, ...] | None = None,
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
        best = (
            preferred
            if preferred in choices
            else min(
                choices,
                key=lambda index: (
                    abs(_cells(cleaned[:index]) / total - target)
                    - _boundary_bonus(cleaned, index)
                    + (0.20 if cleaned[index] in "的了着过" else 0)
                    + (0.08 if cleaned[index - 1] in "的了着过" else 0),
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


def _wrap_lines(text: str, limit: int) -> str:
    if _cells(text) <= limit:
        return text
    lines: list[str] = []
    rest = text
    while _cells(rest) > limit:
        candidates = [
            index
            for index in range(1, len(rest))
            if _safe_break(rest, index) and _cells(rest[:index]) <= limit
        ]
        if not candidates:
            break
        best = min(
            candidates,
            key=lambda index: (
                abs(_cells(rest[:index]) - limit) / limit
                - _boundary_bonus(rest, index) / 2
            ),
        )
        lines.append(rest[:best].strip())
        rest = rest[best:].strip()
    lines.append(rest)
    return "\n".join(lines)


def _word_groups(
    words: tuple[MappedWord, ...], count: int
) -> tuple[tuple[MappedWord, ...], ...]:
    if count == 1:
        return (words,)
    start, end = words[0].start_ms, words[-1].end_ms
    duration = max(1, end - start)
    total = sum(_cells(word.text) + 1 for word in words)
    boundaries = [0]
    for page in range(1, count):
        remaining = count - page
        choices = range(boundaries[-1] + 1, len(words) - remaining + 1)

        def score(index: int, target: float = page / count) -> float:
            current = words[index - 1]
            time_ratio = (current.end_ms - start) / duration
            text_ratio = sum(_cells(word.text) + 1 for word in words[:index]) / total
            pause_ms = words[index].start_ms - current.end_ms
            bonus = (
                _boundary_bonus(current.text, len(current.text)) if current.text else 0
            )
            if pause_ms >= 180:
                bonus += 0.12
            return abs(time_ratio - target) + abs(text_ratio - target) - bonus

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
) -> tuple[SubtitlePage, ...]:
    """Page saved text without changing either language or the source media."""
    available_width = min(horizontal_percent, 100 - horizontal_percent) / 50
    source_limit = max(
        8, round((26 if portrait else 43) * available_width / source_scale)
    )
    translation_limit = max(
        8, round((22 if portrait else 46) * available_width / translation_scale)
    )
    source = " ".join(source.split())
    translation = " ".join(translation.split())
    desired = max(
        ceil(_cells(source) / source_limit) if bilingual else 1,
        ceil(_cells(translation) / translation_limit),
    )
    duration = end_ms - start_ms
    count = min(desired, max(1, duration // 1_100))
    if words and bilingual:
        count = min(count, len(words))
    if words and bilingual:
        groups = _word_groups(words, count)
        source_parts = tuple(
            normalize_text(" ".join(w.text for w in group)) for group in groups
        )
        ends = tuple(group[-1].end_ms for group in groups[:-1]) + (end_ms,)
    else:
        source_parts = _partition_text(source, count) if bilingual else ("",) * count
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
    translated_parts = _partition_text(
        translation,
        count,
        targets,
        stable_limit=translation_limit,
        preferred_edges=preferred_edges,
    )
    pages: list[SubtitlePage] = []
    cursor = start_ms
    for source_part, translated_part, end in zip(
        source_parts, translated_parts, ends, strict=True
    ):
        end = min(end_ms, max(cursor + 1, end))
        pages.append(
            SubtitlePage(
                cursor,
                end,
                _wrap_lines(source_part, source_limit) if bilingual else "",
                _wrap_lines(translated_part, translation_limit),
                translation_language,
            )
        )
        cursor = end
    return tuple(pages)
