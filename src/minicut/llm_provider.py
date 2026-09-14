"""Replaceable asynchronous text-model provider boundary."""

from dataclasses import asdict, dataclass, field
from typing import Protocol, cast


@dataclass(frozen=True, slots=True)
class ModelUsage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    prompt_cache_hit_tokens: int | None = None
    prompt_cache_miss_tokens: int | None = None

    def to_dict(self) -> dict[str, int | None]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: object) -> "ModelUsage":
        data = cast(dict[str, object], value) if isinstance(value, dict) else {}

        def count(key: str) -> int | None:
            item = data.get(key)
            return item if type(item) is int and item >= 0 else None

        return cls(*(count(key) for key in cls.__dataclass_fields__))


class TextModelProviderError(Exception):
    """Base failure reported by a concrete text-model adapter."""

    def __init__(
        self,
        message: str,
        *,
        usage: ModelUsage | None = None,
        finish_reason: str | None = None,
    ) -> None:
        super().__init__(message)
        self.usage = usage or ModelUsage()
        self.finish_reason = finish_reason


class TextModelRateLimitError(TextModelProviderError):
    """Provider rejected a request because its rate limit was reached."""


@dataclass(slots=True)
class TextModelRequest:
    """Provider-neutral prompts for one text generation request."""

    model: str
    system_prompt: str
    user_prompt: str
    max_output_tokens: int = 4096

    def __post_init__(self) -> None:
        if (
            type(self.max_output_tokens) is not int
            or not 1 <= self.max_output_tokens <= 32768
        ):
            raise ValueError("output token budget must be between 1 and 32768")
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
    usage: ModelUsage = field(default_factory=ModelUsage)
    finish_reason: str | None = None

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
