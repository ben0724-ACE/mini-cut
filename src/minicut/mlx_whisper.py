"""Configuration for the MLX Whisper transcription provider."""

from collections.abc import Mapping
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Protocol, cast

from minicut.errors import MiniCutError, ProcessingError, UserInputError
from minicut.transcript import Transcript, TranscriptSource
from minicut.whisper_mapping import map_whisper_response

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
    transcribe: MlxTranscribeCallable | None = None,
) -> dict[str, object]:
    """Call MLX Whisper with word-level timestamps enabled."""
    backend = transcribe if transcribe is not None else _load_mlx_transcribe()
    try:
        return backend(
            str(source_path),
            path_or_hf_repo=config.model_repository,
            language=config.language,
            initial_prompt=config.initial_prompt,
            word_timestamps=True,
            verbose=False,
        )
    except MiniCutError:
        raise
    except Exception as error:
        raise ProcessingError("MLX Whisper transcription failed") from error


def _load_mlx_transcribe() -> MlxTranscribeCallable:
    try:
        module = import_module("mlx_whisper")
    except (ImportError, OSError) as error:
        raise ProcessingError("MLX Whisper backend is not available") from error

    backend = getattr(module, "transcribe", None)
    if not callable(backend):
        raise ProcessingError("MLX Whisper backend is not available")
    return cast(MlxTranscribeCallable, backend)


def map_mlx_transcription(
    response: Mapping[str, object],
    *,
    asset_id: str,
    config: MlxWhisperConfig,
) -> Transcript:
    """Map an MLX response while keeping provider failures user-safe."""
    try:
        transcript = map_whisper_response(
            response,
            source=TranscriptSource(
                asset_id=asset_id,
                provider="mlx-whisper",
                model=config.model_name,
            ),
        )
    except (ArithmeticError, AttributeError, KeyError, TypeError, ValueError) as error:
        raise ProcessingError(
            "MLX Whisper returned invalid or incomplete word timestamps"
        ) from error

    if not transcript.words:
        raise ProcessingError("MLX Whisper returned no timestamped words")
    return transcript


__all__ = [
    "MlxTranscribeCallable",
    "MlxWhisperConfig",
    "map_mlx_transcription",
    "resolve_mlx_model_repository",
    "transcribe_with_mlx",
]
