"""Deterministic construction of initial semantic segments."""

from dataclasses import replace
from itertools import pairwise

from minicut.semantic_segment import SegmentLabel, SemanticSegment, generate_segment_id
from minicut.transcript import Transcript, Utterance

_EXPLICIT_SILENCE_MARKERS = frozenset(
    {"[silence]", "(silence)", "<silence>", "[静音]", "【静音】", "（静音）"}
)
_PURE_FILLERS = frozenset({"嗯", "嗯嗯", "呃", "啊", "呃嗯", "um", "uh", "erm", "hmm"})
_FALSE_START_ENDINGS = ("——", "—", "...", "…", "-")


def _validate_utterances(
    transcript: Transcript,
    utterances: tuple[Utterance, ...],
) -> None:
    utterance_ids = tuple(utterance.utterance_id for utterance in utterances)
    if len(set(utterance_ids)) != len(utterance_ids):
        raise ValueError("Utterance IDs must be unique")
    if any(not utterance.text.strip() for utterance in utterances):
        raise ValueError("Utterance text must not be blank")

    expected_word_ids = tuple(word.word_id for word in transcript.words)
    covered_word_ids = tuple(
        word_id for utterance in utterances for word_id in utterance.word_ids
    )
    if covered_word_ids != expected_word_ids:
        raise ValueError(
            "Utterance Word coverage must match Transcript words once in source order"
        )

    words_by_id = {word.word_id: word for word in transcript.words}
    for utterance in utterances:
        for word_id in utterance.word_ids:
            word = words_by_id[word_id]
            if word.start_ms < utterance.start_ms or word.end_ms > utterance.end_ms:
                raise ValueError("Utterance Word coverage must fit its time range")

    for previous, current in pairwise(utterances):
        if current.start_ms < previous.end_ms:
            raise ValueError("Utterance time ranges must not overlap")


def build_rule_based_segments(
    transcript: Transcript,
    utterances: tuple[Utterance, ...],
) -> tuple[SemanticSegment, ...]:
    """Create one traceable semantic segment for each validated utterance."""
    _validate_utterances(transcript, utterances)
    return tuple(
        SemanticSegment(
            segment_id=generate_segment_id(transcript.transcript_id, ordinal),
            text=utterance.text,
            start_ms=utterance.start_ms,
            end_ms=utterance.end_ms,
            utterance_ids=(utterance.utterance_id,),
            word_ids=utterance.word_ids,
        )
        for ordinal, utterance in enumerate(utterances)
    )


def _canonical_comparison_text(text: str) -> str:
    return "".join(character for character in text.casefold() if character.isalnum())


def mark_segment_candidates(
    segments: tuple[SemanticSegment, ...],
) -> tuple[SemanticSegment, ...]:
    """Return segments with conservative rule-based candidate labels."""
    marked: list[SemanticSegment] = []
    previous_text = ""
    for segment in segments:
        stripped_text = segment.text.strip()
        canonical_text = _canonical_comparison_text(stripped_text)
        labels: list[SegmentLabel] = []
        if stripped_text.casefold() in _EXPLICIT_SILENCE_MARKERS:
            labels.append(SegmentLabel.SILENCE)
        if canonical_text in _PURE_FILLERS:
            labels.append(SegmentLabel.FILLER)
        if stripped_text.endswith(_FALSE_START_ENDINGS):
            labels.append(SegmentLabel.FALSE_START)
        if canonical_text and canonical_text == previous_text:
            labels.append(SegmentLabel.REPETITION_CANDIDATE)
        if not labels:
            labels.append(SegmentLabel.CONTENT)

        marked.append(replace(segment, labels=tuple(labels)))
        previous_text = canonical_text

    return tuple(marked)


__all__ = ["build_rule_based_segments", "mark_segment_candidates"]
