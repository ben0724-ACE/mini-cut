"""Deterministic construction of initial semantic segments."""

from itertools import pairwise

from minicut.semantic_segment import SemanticSegment, generate_segment_id
from minicut.transcript import Transcript, Utterance


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


__all__ = ["build_rule_based_segments"]
