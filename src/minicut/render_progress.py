"""Parse FFmpeg ``-progress`` key-value output into typed events."""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum


class FfmpegProgressState(StrEnum):
    """Lifecycle values emitted by FFmpeg's progress protocol."""

    CONTINUE = "continue"
    END = "end"


@dataclass(frozen=True, slots=True)
class FfmpegProgressEvent:
    """One complete FFmpeg progress report normalized to milliseconds."""

    out_time_ms: int
    state: FfmpegProgressState
    frame: int | None = None
    fps: float | None = None
    speed: float | None = None

    def completion(self, duration_ms: int) -> float:
        """Return a 0..1 completion ratio for a known positive duration."""
        if duration_ms <= 0:
            raise ValueError("render duration must be positive")
        if self.state is FfmpegProgressState.END:
            return 1.0
        return min(max(self.out_time_ms / duration_ms, 0.0), 1.0)


def _optional_int(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _optional_float(value: str | None, *, suffix: str = "") -> float | None:
    if value is None:
        return None
    if suffix and value.endswith(suffix):
        value = value[: -len(suffix)]
    try:
        return float(value)
    except ValueError:
        return None


def _out_time_ms(values: dict[str, str]) -> int:
    microseconds = values.get("out_time_us", values.get("out_time_ms"))
    parsed_microseconds = _optional_int(microseconds)
    if parsed_microseconds is not None:
        return max(parsed_microseconds // 1_000, 0)

    clock = values.get("out_time")
    if clock is None:
        return 0
    try:
        hours, minutes, seconds = clock.split(":", 2)
        return max(
            round((int(hours) * 3_600 + int(minutes) * 60 + float(seconds)) * 1_000),
            0,
        )
    except ValueError:
        return 0


class FfmpegProgressParser:
    """Incrementally assemble line-oriented FFmpeg progress reports."""

    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    def feed_line(self, raw_line: str) -> FfmpegProgressEvent | None:
        """Consume one line and return an event when a report is complete."""
        line = raw_line.strip()
        key, separator, value = line.partition("=")
        if separator != "=" or not key:
            return None
        self._values[key] = value
        if key != "progress":
            return None
        try:
            state = FfmpegProgressState(value)
        except ValueError:
            return None
        event = FfmpegProgressEvent(
            out_time_ms=_out_time_ms(self._values),
            state=state,
            frame=_optional_int(self._values.get("frame")),
            fps=_optional_float(self._values.get("fps")),
            speed=_optional_float(self._values.get("speed"), suffix="x"),
        )
        self._values = {}
        return event


def parse_ffmpeg_progress(lines: Iterable[str]) -> tuple[FfmpegProgressEvent, ...]:
    """Parse zero or more complete progress reports from line-oriented output."""
    parser = FfmpegProgressParser()
    events: list[FfmpegProgressEvent] = []
    for raw_line in lines:
        event = parser.feed_line(raw_line)
        if event is not None:
            events.append(event)
    return tuple(events)


__all__ = [
    "FfmpegProgressEvent",
    "FfmpegProgressParser",
    "FfmpegProgressState",
    "parse_ffmpeg_progress",
]
