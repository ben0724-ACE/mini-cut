"""Configuration for the MLX Whisper transcription provider."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from minicut.errors import UserInputError

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


__all__ = [
    "MlxTranscribeCallable",
    "MlxWhisperConfig",
    "resolve_mlx_model_repository",
    "transcribe_with_mlx",
]
