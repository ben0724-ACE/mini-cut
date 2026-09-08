"""Replaceable asynchronous text-model provider boundary."""

from dataclasses import dataclass
from typing import Protocol


class TextModelProviderError(Exception):
    """Base failure reported by a concrete text-model adapter."""


class TextModelRateLimitError(TextModelProviderError):
    """Provider rejected a request because its rate limit was reached."""


@dataclass(slots=True)
class TextModelRequest:
    """Provider-neutral prompts for one text generation request."""

    model: str
    system_prompt: str
    user_prompt: str

    def __post_init__(self) -> None:
        if not self.model.strip():
            raise ValueError("text model request model must not be blank")
        if not self.system_prompt.strip():
            raise ValueError("text model system prompt must not be blank")
        if not self.user_prompt.strip():
            raise ValueError("text model user prompt must not be blank")


@dataclass(slots=True)
class TextModelResponse:
    """Raw textual result and the model that actually produced it."""

    content: str
    model: str

    def __post_init__(self) -> None:
        if not self.content.strip():
            raise ValueError("text model response content must not be blank")
        if not self.model.strip():
            raise ValueError("text model response model must not be blank")


class TextModelProvider(Protocol):
    """Asynchronous interface implemented by local or remote model adapters."""

    async def generate(self, request: TextModelRequest) -> TextModelResponse:
        """Generate one text response without exposing provider credentials."""
        ...


__all__ = [
    "TextModelProvider",
    "TextModelProviderError",
    "TextModelRateLimitError",
    "TextModelRequest",
    "TextModelResponse",
]
