"""Shared mapping from Whisper-shaped responses to Transcript v1."""

from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal
from typing import cast

from minicut.transcript import (
    Transcript,
    TranscriptSource,
    Utterance,
    Word,
    generate_transcript_id,
    generate_utterance_id,
    generate_word_id,
)


def _seconds_to_milliseconds(value: object) -> int:
    seconds = Decimal(str(value))
    return int((seconds * 1_000).to_integral_value(rounding=ROUND_HALF_UP))


def map_whisper_response(
    response: Mapping[str, object],
    *,
    source: TranscriptSource,
) -> Transcript:
    """Map one valid Whisper-shaped response to Transcript v1."""
    language = cast(str, response["language"])
    transcript_id = generate_transcript_id(source, language)
    raw_segments = cast(list[dict[str, object]], response["segments"])
    words: list[Word] = []
    utterances: list[Utterance] = []

    for segment_ordinal, raw_segment in enumerate(raw_segments):
        raw_words = cast(list[dict[str, object]], raw_segment["words"])
        segment_word_ids: list[str] = []
        for raw_word in raw_words:
            text = cast(str, raw_word["word"]).strip()
            start_ms = _seconds_to_milliseconds(raw_word["start"])
            end_ms = _seconds_to_milliseconds(raw_word["end"])
            word_id = generate_word_id(
                transcript_id,
                len(words),
                text=text,
                start_ms=start_ms,
                end_ms=end_ms,
            )
            words.append(
                Word(
                    word_id=word_id,
                    text=text,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    probability=cast(float, raw_word["probability"]),
                )
            )
            segment_word_ids.append(word_id)

        utterance_text = cast(str, raw_segment["text"]).strip()
        utterance_start_ms = _seconds_to_milliseconds(raw_segment["start"])
        utterance_end_ms = _seconds_to_milliseconds(raw_segment["end"])
        word_ids = tuple(segment_word_ids)
        utterances.append(
            Utterance(
                utterance_id=generate_utterance_id(
                    transcript_id,
                    segment_ordinal,
                    text=utterance_text,
                    start_ms=utterance_start_ms,
                    end_ms=utterance_end_ms,
                    word_ids=word_ids,
                ),
                text=utterance_text,
                start_ms=utterance_start_ms,
                end_ms=utterance_end_ms,
                word_ids=word_ids,
            )
        )

    return Transcript(
        transcript_id=transcript_id,
        source=source,
        language=language,
        words=tuple(words),
        utterances=tuple(utterances),
    )


__all__ = ["map_whisper_response"]
