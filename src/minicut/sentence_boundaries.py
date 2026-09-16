"""Word-traceable planning units; forced size limits are not sentence boundaries."""

from minicut.semantic_segment import SemanticSegment
from minicut.text_normalization import normalize_text
from minicut.transcript import Transcript


def sentence_segments(transcript: Transcript) -> tuple[SemanticSegment, ...]:
    words = transcript.words
    if not words:
        return ()
    # A pause is evidence, not a claim that ASR text is semantically complete.
    edges = {0, len(words)}
    for i, word in enumerate(words[:-1]):
        if (
            word.text.rstrip().endswith(tuple("。！？.!?"))
            or words[i + 1].start_ms - word.end_ms >= 800
        ):
            edges.add(i + 1)
    spans: list[tuple[int, int]] = []
    start = 0
    for end in range(1, len(words) + 1):
        if end in edges or words[end - 1].end_ms - words[start].start_ms >= 15000:
            spans.append((start, end))
            start = end
    return tuple(
        SemanticSegment(
            f"sentence-v1-{a}-{b}-s{int(a in edges)}-e{int(b in edges)}",
            normalize_text(" ".join(w.text for w in words[a:b])),
            words[a].start_ms,
            words[b - 1].end_ms,
            tuple(
                u.utterance_id
                for u in transcript.utterances
                if u.start_ms < words[b - 1].end_ms and u.end_ms > words[a].start_ms
            )
            or (f"words-{a}-{b}",),
            tuple(w.word_id for w in words[a:b]),
        )
        for a, b in spans
    )


def complete_range(
    body: list[SemanticSegment], segments: tuple[SemanticSegment, ...]
) -> tuple[int, int, tuple[str, ...]]:
    start, end = body[0].start_ms, body[-1].end_ms
    notes: list[str] = []
    if body[0].segment_id.startswith("sentence-v1-"):
        starts = [
            s.start_ms
            for s in segments
            if "-s1-" in s.segment_id and start - 10000 <= s.start_ms <= start
        ]
        ends = [
            s.end_ms
            for s in segments
            if s.segment_id.endswith("-e1") and end <= s.end_ms <= end + 10000
        ]
        if starts:
            start = max(starts)
        else:
            notes.append("建议检查开头：10 秒内未发现可靠句界")
        if ends:
            end = min(ends)
        else:
            notes.append("建议检查结尾：10 秒内未发现可靠句界")
    previous_end = max((s.end_ms for s in segments if s.end_ms <= start), default=0)
    following_start = min(
        (s.start_ms for s in segments if s.start_ms >= end), default=end + 100
    )
    return (
        max(0, start - 100, previous_end),
        min(end + 100, following_start),
        tuple(notes),
    )
