"""Configuration for the MLX Whisper transcription provider."""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Protocol, cast

from minicut.errors import UserInputError
from minicut.transcript import (
    Transcript,
    TranscriptSource,
    Utterance,
    Word,
    generate_transcript_id,
    generate_utterance_id,
    generate_word_id,
)

_MODEL_REPOSITORIES = {
    "tiny": "mlx-community/whisper-tiny",
    "base": "mlx-community/whisper-base-mlx",
    "small": "mlx-community/whisper-small-mlx",
    "medium": "mlx-community/whisper-medium-mlx",
    "large": "mlx-community/whisper-large-v3-mlx",
    "large-v2": "mlx-community/whisper-large-v2-mlx",
    "large-v3": "mlx-community/whisper-large-v3-mlx",
    "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
}


class MlxTranscribeCallable(Protocol):
    """Callable subset of the mlx_whisper.transcribe API used by MiniCut."""

    def __call__(
        self,
        audio: str,
        *,
        path_or_hf_repo: str,
        language: str,
        initial_prompt: str | None,
        word_timestamps: bool,
        verbose: bool,
    ) -> dict[str, object]:
        """Return the raw MLX Whisper transcription response."""
        ...


def resolve_mlx_model_repository(model_name: str) -> str:
    """Resolve a supported short model name to its MLX repository."""
    try:
        return _MODEL_REPOSITORIES[model_name]
    except KeyError:
        supported = ", ".join(sorted(_MODEL_REPOSITORIES))
        raise UserInputError(
            f"Unsupported MLX Whisper model {model_name!r}. "
            f"Supported models: {supported}"
        ) from None


@dataclass(slots=True)
class MlxWhisperConfig:
    """User-controlled settings for one MLX Whisper transcription."""

    model_name: str = "large-v3-turbo"
    language: str = "zh"
    initial_prompt: str | None = None

    def __post_init__(self) -> None:
        resolve_mlx_model_repository(self.model_name)
        if not self.language.strip():
            raise ValueError("language must not be blank")

    @property
    def model_repository(self) -> str:
        """Return the repository expected by mlx_whisper.transcribe."""
        return resolve_mlx_model_repository(self.model_name)


def transcribe_with_mlx(
    source_path: str | Path,
    config: MlxWhisperConfig,
    *,
    transcribe: MlxTranscribeCallable,
) -> dict[str, object]:
    """Call MLX Whisper with word-level timestamps enabled."""
    return transcribe(
        str(source_path),
        path_or_hf_repo=config.model_repository,
        language=config.language,
        initial_prompt=config.initial_prompt,
        word_timestamps=True,
        verbose=False,
    )


def _seconds_to_milliseconds(value: object) -> int:
    seconds = Decimal(str(value))
    return int((seconds * 1_000).to_integral_value(rounding=ROUND_HALF_UP))


def map_mlx_transcription(
    response: Mapping[str, object],
    *,
    asset_id: str,
    config: MlxWhisperConfig,
) -> Transcript:
    """Map a valid raw MLX Whisper response to Transcript v1."""
    language = cast(str, response["language"])
    source = TranscriptSource(
        asset_id=asset_id,
        provider="mlx-whisper",
        model=config.model_name,
    )
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


__all__ = [
    "MlxTranscribeCallable",
    "MlxWhisperConfig",
    "map_mlx_transcription",
    "resolve_mlx_model_repository",
    "transcribe_with_mlx",
]
