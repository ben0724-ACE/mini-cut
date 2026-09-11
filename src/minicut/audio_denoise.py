"""Pluggable audio denoiser providers for FFmpeg render filters."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol


class AudioDenoiser(Protocol):
    @property
    def provider_id(self) -> str: ...

    def ffmpeg_filter(self) -> str: ...


def _validate_provider_id(value: str) -> None:
    if not value or any(
        character
        not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
        for character in value
    ):
        raise ValueError("denoiser provider ID must be an opaque identifier")


@dataclass(frozen=True, slots=True)
class FfmpegAudioDenoiser:
    provider_id: str
    filter_expression: str

    def __post_init__(self) -> None:
        _validate_provider_id(self.provider_id)
        if not self.filter_expression.strip() or "\0" in self.filter_expression:
            raise ValueError("denoiser filter expression must not be blank")

    def ffmpeg_filter(self) -> str:
        return self.filter_expression


_BUILTIN_DENOISERS: tuple[AudioDenoiser, ...] = (
    FfmpegAudioDenoiser("afftdn", "afftdn=nr=12:nf=-50"),
)


def build_denoiser_registry(
    providers: tuple[AudioDenoiser, ...] = (),
) -> Mapping[str, AudioDenoiser]:
    registry: dict[str, AudioDenoiser] = {}
    for provider in (*_BUILTIN_DENOISERS, *providers):
        _validate_provider_id(provider.provider_id)
        if provider.provider_id in registry:
            raise ValueError("duplicate denoiser provider ID")
        if not provider.ffmpeg_filter().strip():
            raise ValueError("denoiser filter expression must not be blank")
        registry[provider.provider_id] = provider
    return MappingProxyType(registry)


def resolve_denoiser(
    provider_id: str,
    registry: Mapping[str, AudioDenoiser],
) -> AudioDenoiser | None:
    if provider_id == "none":
        return None
    try:
        return registry[provider_id]
    except KeyError as error:
        raise ValueError(f"unknown denoiser provider: {provider_id}") from error


__all__ = [
    "AudioDenoiser",
    "FfmpegAudioDenoiser",
    "build_denoiser_registry",
    "resolve_denoiser",
]
