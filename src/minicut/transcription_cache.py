"""Structured identity for reusable transcription results."""

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import cast

from minicut.errors import ProcessingError
from minicut.mlx_whisper import MlxWhisperConfig
from minicut.open_source_whisper import OpenSourceWhisperConfig
from minicut.transcript import Transcript


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

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""
        return {
            "media_fingerprint": self.media_fingerprint,
            "provider": self.provider,
            "model": self.model,
            "language": self.language,
            "initial_prompt": self.initial_prompt,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "TranscriptionCacheKey":
        """Restore a structured key from a JSON-compatible mapping."""
        return cls(
            media_fingerprint=cast(str, data["media_fingerprint"]),
            provider=cast(str, data["provider"]),
            model=cast(str, data["model"]),
            language=cast(str, data["language"]),
            initial_prompt=cast(str | None, data["initial_prompt"]),
        )


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


CacheProducer = Callable[[], Transcript]
CacheFileReplacer = Callable[[Path, Path], None]


def _replace_cache_file(source: Path, destination: Path) -> None:
    source.replace(destination)


class TranscriptCacheRepository:
    """Persist one keyed Transcript entry at an explicit local path."""

    def __init__(
        self,
        cache_path: str | Path,
        *,
        replace_file: CacheFileReplacer = _replace_cache_file,
    ) -> None:
        self.cache_path = Path(cache_path)
        self._replace_file = replace_file

    def read(self, key: TranscriptionCacheKey) -> Transcript | None:
        """Return a matching cached Transcript, or None for a miss."""
        if not self.cache_path.is_file():
            return None
        try:
            data = cast(
                dict[str, object],
                json.loads(self.cache_path.read_text(encoding="utf-8")),
            )
            key_data = cast(dict[str, object], data["key"])
            if TranscriptionCacheKey.from_dict(key_data) != key:
                return None
            transcript_data = cast(dict[str, object], data["transcript"])
            return Transcript.from_dict(transcript_data)
        except (
            AttributeError,
            KeyError,
            OSError,
            TypeError,
            UnicodeError,
            ValueError,
        ) as error:
            raise ProcessingError("Transcription cache is invalid") from error

    def write(self, key: TranscriptionCacheKey, transcript: Transcript) -> None:
        """Atomically publish one complete cache entry."""
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self._write(key, transcript)
        except OSError as error:
            raise ProcessingError("Transcription cache could not be written") from error

    def get_or_create(
        self,
        key: TranscriptionCacheKey,
        producer: CacheProducer,
    ) -> Transcript:
        """Return a cache hit or produce and persist a new Transcript."""
        cached = self.read(key)
        if cached is not None:
            return cached
        transcript = producer()
        self.write(key, transcript)
        return transcript

    def _write(self, key: TranscriptionCacheKey, transcript: Transcript) -> None:
        temporary_path: Path | None = None
        try:
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.cache_path.parent,
                prefix=f".{self.cache_path.name}-",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                json.dump(
                    {"key": key.to_dict(), "transcript": transcript.to_dict()},
                    temporary_file,
                    ensure_ascii=False,
                )
                temporary_file.write("\n")
                temporary_path = Path(temporary_file.name)
            self._replace_file(temporary_path, self.cache_path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)


__all__ = [
    "CacheFileReplacer",
    "CacheProducer",
    "TranscriptCacheRepository",
    "TranscriptionCacheKey",
    "cache_key_for_mlx",
    "cache_key_for_open_source_whisper",
]
