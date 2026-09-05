"""Media domain models with millisecond time values."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from hashlib import file_digest
from pathlib import Path, PurePath
from typing import cast

from minicut.errors import UserInputError

_VIDEO_EXTENSIONS = frozenset({".mp4", ".mov", ".mkv", ".avi", ".flv", ".f4v", ".webm"})
_AUDIO_EXTENSIONS = frozenset({".ogg", ".wav", ".mp3", ".flac", ".m4a"})


@dataclass(slots=True)
class TimeRange:
    """A non-empty time range measured in integer milliseconds."""

    start_ms: int
    end_ms: int

    def __post_init__(self) -> None:
        if self.start_ms < 0:
            raise ValueError("start_ms must not be negative")
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")

    @property
    def duration_ms(self) -> int:
        """Return the range duration in milliseconds."""
        return self.end_ms - self.start_ms


class StreamType(StrEnum):
    """Media stream types supported by MiniCut."""

    AUDIO = "audio"
    VIDEO = "video"


def classify_media(source_path: str, mime_type: str | None = None) -> StreamType:
    """Classify a supported media path and validate an optional MIME type."""
    extension = PurePath(source_path).suffix.casefold()
    if extension in _VIDEO_EXTENSIONS:
        stream_type = StreamType.VIDEO
    elif extension in _AUDIO_EXTENSIONS:
        stream_type = StreamType.AUDIO
    else:
        displayed_extension = extension or "<none>"
        raise UserInputError(f"Unsupported media extension: {displayed_extension}")

    if mime_type is not None:
        normalized_mime = mime_type.partition(";")[0].strip().casefold()
        mime_category, separator, mime_subtype = normalized_mime.partition("/")
        if separator != "/" or not mime_subtype or mime_category != stream_type.value:
            raise UserInputError(
                f"MIME type {mime_type!r} does not match extension {extension}"
            )

    return stream_type


def fingerprint_media(source_path: str | Path) -> str:
    """Return a stable fingerprint for the complete media file content."""
    with Path(source_path).open("rb") as media_file:
        digest = file_digest(media_file, "sha256").hexdigest()
    return f"sha256:{digest}"


def _validate_stream_type(value: object) -> None:
    if not isinstance(value, StreamType):
        raise ValueError("stream_type must be audio or video")


@dataclass(slots=True)
class StreamInfo:
    """Normalized information about one audio or video stream."""

    index: int
    stream_type: StreamType
    codec_name: str

    def __post_init__(self) -> None:
        _validate_stream_type(self.stream_type)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""
        return {
            "index": self.index,
            "stream_type": self.stream_type.value,
            "codec_name": self.codec_name,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "StreamInfo":
        """Restore stream information from a JSON-compatible mapping."""
        return cls(
            index=cast(int, data["index"]),
            stream_type=StreamType(cast(str, data["stream_type"])),
            codec_name=cast(str, data["codec_name"]),
        )


@dataclass(slots=True)
class MediaAsset:
    """Normalized metadata for one source media asset."""

    asset_id: str
    source_path: str
    duration_ms: int
    streams: tuple[StreamInfo, ...]
    content_fingerprint: str

    def __post_init__(self) -> None:
        if not self.asset_id.strip():
            raise ValueError("asset_id must not be empty")
        if self.duration_ms < 0:
            raise ValueError("duration_ms must not be negative")

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""
        return {
            "asset_id": self.asset_id,
            "source_path": self.source_path,
            "duration_ms": self.duration_ms,
            "streams": [stream.to_dict() for stream in self.streams],
            "content_fingerprint": self.content_fingerprint,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "MediaAsset":
        """Restore an asset from a JSON-compatible mapping."""
        stream_data = cast(list[dict[str, object]], data["streams"])
        return cls(
            asset_id=cast(str, data["asset_id"]),
            source_path=cast(str, data["source_path"]),
            duration_ms=cast(int, data["duration_ms"]),
            streams=tuple(StreamInfo.from_dict(item) for item in stream_data),
            content_fingerprint=cast(str, data["content_fingerprint"]),
        )


__all__ = [
    "MediaAsset",
    "StreamInfo",
    "StreamType",
    "TimeRange",
    "classify_media",
    "fingerprint_media",
]
