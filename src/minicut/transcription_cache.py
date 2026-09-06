"""Structured identity for reusable transcription results."""

from dataclasses import dataclass

from minicut.mlx_whisper import MlxWhisperConfig
from minicut.open_source_whisper import OpenSourceWhisperConfig


@dataclass(slots=True)
class TranscriptionCacheKey:
    """Inputs that determine whether a Transcript result can be reused."""

    media_fingerprint: str
    provider: str
    model: str
    language: str
    initial_prompt: str | None

    def __post_init__(self) -> None:
        required_fields = (
            ("media_fingerprint", self.media_fingerprint),
            ("provider", self.provider),
            ("model", self.model),
            ("language", self.language),
        )
        for field_name, value in required_fields:
            if not value.strip():
                raise ValueError(f"{field_name} must not be blank")


def cache_key_for_mlx(
    media_fingerprint: str,
    config: MlxWhisperConfig,
) -> TranscriptionCacheKey:
    """Build the structured cache identity for one MLX transcription."""
    return TranscriptionCacheKey(
        media_fingerprint=media_fingerprint,
        provider="mlx-whisper",
        model=config.model_name,
        language=config.language,
        initial_prompt=config.initial_prompt,
    )


def cache_key_for_open_source_whisper(
    media_fingerprint: str,
    config: OpenSourceWhisperConfig,
) -> TranscriptionCacheKey:
    """Build the structured cache identity for one open-source transcription."""
    return TranscriptionCacheKey(
        media_fingerprint=media_fingerprint,
        provider="open-source-whisper",
        model=config.model_name,
        language=config.language,
        initial_prompt=config.initial_prompt,
    )


__all__ = [
    "TranscriptionCacheKey",
    "cache_key_for_mlx",
    "cache_key_for_open_source_whisper",
]
