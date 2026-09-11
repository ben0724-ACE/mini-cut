"""Map retained transcript words onto rendered timeline time."""

import re
import unicodedata
from dataclasses import dataclass

from minicut.semantic_segment import SemanticSegment
from minicut.timeline import Timeline
from minicut.transcript import Word


@dataclass(frozen=True, slots=True)
class MappedWord:
    """One retained transcript token translated to output time."""

    word_id: str
    text: str
    start_ms: int
    end_ms: int
    clip_id: str

    def __post_init__(self) -> None:
        if not self.word_id.strip() or not self.clip_id.strip():
            raise ValueError("mapped Word and Clip IDs must not be blank")
        if self.start_ms < 0 or self.end_ms <= self.start_ms:
            raise ValueError("mapped Word time range must be non-empty")


@dataclass(frozen=True, slots=True)
class SubtitleTermCorrection:
    """One exact transcript-token sequence and its preferred display text."""

    source_tokens: tuple[str, ...]
    replacement: str

    def __post_init__(self) -> None:
        if not self.source_tokens or any(
            not token.strip() for token in self.source_tokens
        ):
            raise ValueError("subtitle correction source tokens must not be blank")
        if not self.replacement.strip():
            raise ValueError("subtitle correction replacement must not be blank")


def correct_subtitle_terms(
    mapped_words: tuple[MappedWord, ...],
    corrections: tuple[SubtitleTermCorrection, ...],
) -> tuple[MappedWord, ...]:
    """Apply display-only terminology fixes without modifying a transcript."""
    sources = tuple(correction.source_tokens for correction in corrections)
    if len(set(sources)) != len(sources):
        raise ValueError("subtitle correction source tokens must not be duplicate")
    ordered = tuple(
        sorted(
            corrections,
            key=lambda correction: len(correction.source_tokens),
            reverse=True,
        )
    )
    corrected: list[MappedWord] = []
    index = 0
    while index < len(mapped_words):
        match: tuple[SubtitleTermCorrection, tuple[MappedWord, ...]] | None = None
        for correction in ordered:
            count = len(correction.source_tokens)
            candidates = mapped_words[index : index + count]
            if len(candidates) != count:
                continue
            if tuple(word.text for word in candidates) != correction.source_tokens:
                continue
            if len({word.clip_id for word in candidates}) != 1:
                continue
            match = correction, candidates
            break
        if match is None:
            corrected.append(mapped_words[index])
            index += 1
            continue
        correction, candidates = match
        corrected.append(
            MappedWord(
                candidates[0].word_id,
                correction.replacement,
                candidates[0].start_ms,
                candidates[-1].end_ms,
                candidates[0].clip_id,
            )
        )
        index += len(candidates)
    return tuple(corrected)


@dataclass(frozen=True, slots=True)
class SubtitleCue:
    """One non-empty subtitle interval ready for serialization."""

    start_ms: int
    end_ms: int
    text: str

    def __post_init__(self) -> None:
        if self.start_ms < 0 or self.end_ms <= self.start_ms:
            raise ValueError("subtitle cue time range must be non-empty")
        if not self.text.strip():
            raise ValueError("subtitle cue text must not be blank")


@dataclass(frozen=True, slots=True)
class SubtitleLayoutPolicy:
    """Readable line and duration constraints for grouped subtitle cues."""

    max_characters_per_line: int = 18
    max_lines: int = 2
    min_duration_ms: int = 800
    max_duration_ms: int = 5_000
    normalize_chinese_punctuation: bool = True

    def __post_init__(self) -> None:
        if self.max_characters_per_line <= 0 or self.max_lines <= 0:
            raise ValueError("subtitle line limits must be positive")
        if self.min_duration_ms <= 0 or self.max_duration_ms <= 0:
            raise ValueError("subtitle duration limits must be positive")
        if self.min_duration_ms > self.max_duration_ms:
            raise ValueError("subtitle minimum duration must not exceed maximum")


_DEFAULT_LAYOUT_POLICY = SubtitleLayoutPolicy()


_TIMESTAMP = re.compile(
    r"^(?P<hours>\d{2,}):(?P<minutes>[0-5]\d):(?P<seconds>[0-5]\d),"
    r"(?P<milliseconds>\d{3})$"
)


def _format_timestamp(milliseconds: int) -> str:
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def _parse_timestamp(value: str) -> int:
    match = _TIMESTAMP.fullmatch(value)
    if match is None:
        raise ValueError("invalid SRT timestamp")
    return (
        int(match["hours"]) * 3_600_000
        + int(match["minutes"]) * 60_000
        + int(match["seconds"]) * 1_000
        + int(match["milliseconds"])
    )


def _validate_cue_sequence(
    cues: tuple[SubtitleCue, ...], video_duration_ms: int
) -> None:
    if video_duration_ms < 0:
        raise ValueError("video duration must not be negative")
    previous_end_ms = 0
    for cue in cues:
        if cue.start_ms < previous_end_ms:
            raise ValueError("subtitle cues must be monotonic and non-overlapping")
        if cue.end_ms > video_duration_ms:
            raise ValueError("subtitle cue exceeds video duration")
        previous_end_ms = cue.end_ms


def build_word_cues(
    mapped_words: tuple[MappedWord, ...], video_duration_ms: int
) -> tuple[SubtitleCue, ...]:
    """Create one strictly timed cue for each retained word."""
    cues = tuple(
        SubtitleCue(word.start_ms, word.end_ms, word.text)
        for word in mapped_words
        if word.text.strip()
    )
    _validate_cue_sequence(cues, video_duration_ms)
    return cues


_TERMINAL_PUNCTUATION = frozenset("。！？!?…")
_CHINESE_PUNCTUATION = {
    ",": "，",
    ".": "。",
    ":": "：",
    ";": "；",
    "!": "！",
    "?": "？",
}


def _is_punctuation(text: str) -> bool:
    return bool(text) and all(
        unicodedata.category(character).startswith("P") for character in text
    )


def _append_token(current: str, token: str) -> str:
    needs_space = (
        bool(current)
        and not _is_punctuation(token)
        and token[0].isascii()
        and token[0].isalnum()
        and (
            (current[-1].isascii() and current[-1].isalnum()) or current[-1] in ",.!?;:"
        )
    )
    return f"{current}{' ' if needs_space else ''}{token}"


def _contains_cjk(text: str) -> bool:
    return any("\u3400" <= character <= "\u9fff" for character in text)


def _normalize_punctuation(tokens: tuple[str, ...]) -> tuple[str, ...]:
    normalized: list[str] = []
    for index, token in enumerate(tokens):
        previous = tokens[index - 1] if index else ""
        following = tokens[index + 1] if index + 1 < len(tokens) else ""
        if token in _CHINESE_PUNCTUATION and (
            _contains_cjk(previous) or _contains_cjk(following)
        ):
            token = _CHINESE_PUNCTUATION[token]
        normalized.append(token)
    return tuple(normalized)


def _join_tokens(tokens: list[str]) -> str:
    text = ""
    for token in tokens:
        text = _append_token(text, token)
    return text


def _wrap_tokens(
    tokens: tuple[str, ...],
    max_characters: int,
    *,
    normalize_chinese_punctuation: bool,
) -> tuple[str, ...]:
    if normalize_chinese_punctuation:
        tokens = _normalize_punctuation(tokens)
    lines: list[list[str]] = []
    for token in tokens:
        if not lines:
            lines.append([token])
            continue
        candidate = _join_tokens([*lines[-1], token])
        if len(candidate) <= max_characters:
            lines[-1].append(token)
        elif _is_punctuation(token) and len(lines[-1]) > 1:
            previous_token = lines[-1].pop()
            lines.append([previous_token, token])
        elif _is_punctuation(token):
            lines[-1].append(token)
        else:
            lines.append([token])
    return tuple(_join_tokens(line) for line in lines)


def build_readable_cues(
    mapped_words: tuple[MappedWord, ...],
    video_duration_ms: int,
    policy: SubtitleLayoutPolicy = _DEFAULT_LAYOUT_POLICY,
) -> tuple[SubtitleCue, ...]:
    """Group mapped words by line, duration, punctuation, and edit boundaries."""
    build_word_cues(mapped_words, video_duration_ms)
    retained = tuple(word for word in mapped_words if word.text.strip())
    if not retained:
        return ()

    groups: list[tuple[MappedWord, ...]] = []
    current: list[MappedWord] = []
    for word in retained:
        if current:
            tokens = tuple(item.text for item in (*current, word))
            exceeds_lines = (
                len(
                    _wrap_tokens(
                        tokens,
                        policy.max_characters_per_line,
                        normalize_chinese_punctuation=(
                            policy.normalize_chinese_punctuation
                        ),
                    )
                )
                > policy.max_lines
            )
            exceeds_duration = (
                word.end_ms - current[0].start_ms > policy.max_duration_ms
            )
            changed_clip = word.clip_id != current[-1].clip_id
            after_sentence = current[-1].text.rstrip()[-1] in _TERMINAL_PUNCTUATION
            if exceeds_lines or exceeds_duration or changed_clip or after_sentence:
                groups.append(tuple(current))
                current = []
        current.append(word)
    groups.append(tuple(current))

    cues: list[SubtitleCue] = []
    for index, group in enumerate(groups):
        start_ms = group[0].start_ms
        natural_end_ms = group[-1].end_ms
        next_start_ms = (
            groups[index + 1][0].start_ms
            if index + 1 < len(groups)
            else video_duration_ms
        )
        end_ms = min(
            max(natural_end_ms, start_ms + policy.min_duration_ms),
            next_start_ms,
            video_duration_ms,
        )
        lines = _wrap_tokens(
            tuple(word.text for word in group),
            policy.max_characters_per_line,
            normalize_chinese_punctuation=policy.normalize_chinese_punctuation,
        )
        cues.append(SubtitleCue(start_ms, end_ms, "\n".join(lines)))
    result = tuple(cues)
    _validate_cue_sequence(result, video_duration_ms)
    return result


def render_srt(cues: tuple[SubtitleCue, ...], video_duration_ms: int) -> str:
    """Serialize validated cues as standards-compatible SubRip text."""
    _validate_cue_sequence(cues, video_duration_ms)
    blocks = (
        f"{index}\n{_format_timestamp(cue.start_ms)} --> "
        f"{_format_timestamp(cue.end_ms)}\n{cue.text}"
        for index, cue in enumerate(cues, start=1)
    )
    rendered = "\n\n".join(blocks)
    return f"{rendered}\n" if rendered else ""


def parse_srt(content: str) -> tuple[SubtitleCue, ...]:
    """Strictly parse SubRip generated by MiniCut for round-trip verification."""
    normalized = content.replace("\r\n", "\n").strip()
    if not normalized:
        return ()
    cues: list[SubtitleCue] = []
    for expected_index, block in enumerate(normalized.split("\n\n"), start=1):
        lines = block.splitlines()
        if len(lines) < 3 or lines[0] != str(expected_index):
            raise ValueError("invalid SRT cue index or content")
        start, separator, end = lines[1].partition(" --> ")
        if separator != " --> ":
            raise ValueError("invalid SRT cue timing")
        cues.append(
            SubtitleCue(
                _parse_timestamp(start),
                _parse_timestamp(end),
                "\n".join(lines[2:]),
            )
        )
    return tuple(cues)


def map_retained_words(
    timeline: Timeline,
    segments: tuple[SemanticSegment, ...],
    words: tuple[Word, ...],
) -> tuple[MappedWord, ...]:
    """Translate only retained Segment words from source to output time."""
    segments_by_id = {segment.segment_id: segment for segment in segments}
    words_by_id = {word.word_id: word for word in words}
    if len(segments_by_id) != len(segments):
        raise ValueError("Segment IDs must be unique for subtitle mapping")
    if len(words_by_id) != len(words):
        raise ValueError("Word IDs must be unique for subtitle mapping")

    mapped: list[MappedWord] = []
    mapped_word_ids: set[str] = set()
    for clip in timeline.clips:
        clip_word_ids: list[str] = []
        for segment_id in clip.segment_ids:
            segment = segments_by_id.get(segment_id)
            if segment is None:
                raise ValueError("Timeline Clip references an unknown Segment")
            clip_word_ids.extend(segment.word_ids)

        clip_words: list[Word] = []
        for word_id in dict.fromkeys(clip_word_ids):
            word = words_by_id.get(word_id)
            if word is None:
                raise ValueError("retained Segment references an unknown Word")
            if word_id in mapped_word_ids:
                raise ValueError("retained Word is mapped by more than one Clip")
            if (
                word.start_ms < clip.source_range.start_ms
                or word.end_ms > clip.source_range.end_ms
            ):
                raise ValueError("retained Word lies outside its Clip source range")
            clip_words.append(word)

        for word in sorted(
            clip_words,
            key=lambda item: (item.start_ms, item.end_ms, item.word_id),
        ):
            offset_ms = clip.output_range.start_ms - clip.source_range.start_ms
            mapped.append(
                MappedWord(
                    word.word_id,
                    word.text,
                    word.start_ms + offset_ms,
                    word.end_ms + offset_ms,
                    clip.clip_id,
                )
            )
            mapped_word_ids.add(word.word_id)
    return tuple(mapped)


__all__ = [
    "MappedWord",
    "SubtitleCue",
    "SubtitleLayoutPolicy",
    "SubtitleTermCorrection",
    "build_readable_cues",
    "build_word_cues",
    "correct_subtitle_terms",
    "map_retained_words",
    "parse_srt",
    "render_srt",
]
