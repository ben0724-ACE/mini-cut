"""Progress reporting and cooperative cancellation for transcription work."""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from threading import Event

from minicut.errors import MiniCutError
from minicut.transcript import Transcript
from minicut.transcription_cache import (
    TranscriptCacheRepository,
    TranscriptionCacheKey,
)


class TranscriptionCancelled(MiniCutError):
    """Raised when a transcription task observes requested cancellation."""


class CancellationToken:
    """Thread-safe cancellation state shared with cooperative producers."""

    def __init__(self) -> None:
        self._cancelled = Event()

    @property
    def is_cancelled(self) -> bool:
        """Return whether cancellation has been requested."""
        return self._cancelled.is_set()

    def cancel(self) -> None:
        """Request cancellation without interrupting the current operation."""
        self._cancelled.set()

    def raise_if_cancelled(self) -> None:
        """Stop at a cooperative cancellation point."""
        if self.is_cancelled:
            raise TranscriptionCancelled("Transcription was cancelled")


class TranscriptionPhase(StrEnum):
    """Observable phases of one cached transcription task."""

    CACHE_LOOKUP = "cache_lookup"
    CACHE_HIT = "cache_hit"
    TRANSCRIBING = "transcribing"
    PERSISTING = "persisting"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class TranscriptionProgressEvent:
    """One observable task phase transition."""

    phase: TranscriptionPhase


TranscriptionProducer = Callable[[CancellationToken], Transcript]
ProgressReporter = Callable[[TranscriptionProgressEvent], None]


def _ignore_progress(event: TranscriptionProgressEvent) -> None:
    del event


def run_transcription_task(
    repository: TranscriptCacheRepository,
    key: TranscriptionCacheKey,
    producer: TranscriptionProducer,
    *,
    cancellation: CancellationToken | None = None,
    on_progress: ProgressReporter = _ignore_progress,
) -> Transcript:
    """Return a cache hit or run cancellable work and publish its result."""
    token = cancellation if cancellation is not None else CancellationToken()

    def advance(phase: TranscriptionPhase) -> None:
        on_progress(TranscriptionProgressEvent(phase=phase))
        token.raise_if_cancelled()

    try:
        token.raise_if_cancelled()
        advance(TranscriptionPhase.CACHE_LOOKUP)
        cached = repository.read(key)
        if cached is not None:
            advance(TranscriptionPhase.CACHE_HIT)
            on_progress(TranscriptionProgressEvent(TranscriptionPhase.COMPLETED))
            return cached

        advance(TranscriptionPhase.TRANSCRIBING)
        transcript = producer(token)
        token.raise_if_cancelled()
        advance(TranscriptionPhase.PERSISTING)
        repository.write(key, transcript)
        on_progress(TranscriptionProgressEvent(TranscriptionPhase.COMPLETED))
        return transcript
    except TranscriptionCancelled:
        on_progress(TranscriptionProgressEvent(TranscriptionPhase.CANCELLED))
        raise


__all__ = [
    "CancellationToken",
    "ProgressReporter",
    "TranscriptionCancelled",
    "TranscriptionPhase",
    "TranscriptionProducer",
    "TranscriptionProgressEvent",
    "run_transcription_task",
]
