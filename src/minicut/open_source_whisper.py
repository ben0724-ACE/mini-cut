"""Open-source Whisper transcription provider."""

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Protocol, cast

from minicut.errors import MiniCutError, ProcessingError, UserInputError

_SUPPORTED_MODELS = frozenset(
    {
        "tiny",
        "tiny.en",
        "base",
        "base.en",
        "small",
        "small.en",
        "medium",
        "medium.en",
        "large",
        "large-v1",
        "large-v2",
        "large-v3",
        "large-v3-turbo",
        "turbo",
    }
)


class OpenSourceWhisperModel(Protocol):
    """Subset of a loaded openai-whisper model used by MiniCut."""

    def transcribe(
        self,
        audio: str,
        *,
        task: str,
        language: str,
        initial_prompt: str | None,
        word_timestamps: bool,
        verbose: bool,
    ) -> dict[str, object]:
        """Return the raw openai-whisper transcription response."""
        ...


class OpenSourceWhisperLoader(Protocol):
    """Callable subset of whisper.load_model used by MiniCut."""

    def __call__(
        self,
        model_name: str,
        *,
        device: str | None,
    ) -> OpenSourceWhisperModel:
        """Load and return one Whisper model."""
        ...


@dataclass(slots=True)
class OpenSourceWhisperConfig:
    """User-controlled settings for open-source Whisper transcription."""

    model_name: str = "small"
    language: str = "zh"
    device: str | None = None
    initial_prompt: str | None = None

    def __post_init__(self) -> None:
        if self.model_name not in _SUPPORTED_MODELS:
            supported = ", ".join(sorted(_SUPPORTED_MODELS))
            raise UserInputError(
                f"Unsupported Whisper model {self.model_name!r}. "
                f"Supported models: {supported}"
            )
        if not self.language.strip():
            raise ValueError("language must not be blank")
        if self.device is not None and not self.device.strip():
            raise ValueError("device must not be blank")


def _load_open_source_whisper_loader() -> OpenSourceWhisperLoader:
    try:
        module = import_module("whisper")
    except (ImportError, OSError) as error:
        raise ProcessingError("open-source Whisper backend is not available") from error

    loader = getattr(module, "load_model", None)
    if not callable(loader):
        raise ProcessingError("open-source Whisper backend is not available")
    return cast(OpenSourceWhisperLoader, loader)


def transcribe_with_open_source_whisper(
    source_path: str | Path,
    config: OpenSourceWhisperConfig,
    *,
    load_model: OpenSourceWhisperLoader | None = None,
) -> dict[str, object]:
    """Load open-source Whisper and transcribe with word timestamps enabled."""
    loader = (
        load_model if load_model is not None else _load_open_source_whisper_loader()
    )
    try:
        model = loader(config.model_name, device=config.device)
    except MiniCutError:
        raise
    except Exception as error:
        raise ProcessingError("open-source Whisper model loading failed") from error

    try:
        return model.transcribe(
            str(source_path),
            task="transcribe",
            language=config.language,
            initial_prompt=config.initial_prompt,
            word_timestamps=True,
            verbose=False,
        )
    except MiniCutError:
        raise
    except Exception as error:
        raise ProcessingError("open-source Whisper transcription failed") from error


__all__ = [
    "OpenSourceWhisperConfig",
    "OpenSourceWhisperLoader",
    "OpenSourceWhisperModel",
    "transcribe_with_open_source_whisper",
]
