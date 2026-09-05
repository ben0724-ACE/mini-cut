"""Build ffprobe requests and parse their JSON output."""

import json
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import cast

from minicut.media import StreamInfo, StreamType

Command = tuple[str, ...]


@dataclass(slots=True)
class ProbeResult:
    """Normalized metadata parsed from one ffprobe response."""

    duration_ms: int
    streams: tuple[StreamInfo, ...]


def build_ffprobe_command(
    source_path: str | Path,
    *,
    executable: str = "ffprobe",
) -> Command:
    """Return arguments that request format and stream metadata as JSON."""
    return (
        executable,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        "-i",
        str(source_path),
    )


def parse_ffprobe_json(output: str) -> ProbeResult:
    """Parse valid ffprobe JSON into normalized media metadata."""
    payload = cast(dict[str, object], json.loads(output))
    format_data = cast(dict[str, object], payload["format"])
    stream_data = cast(list[dict[str, object]], payload["streams"])
    duration_seconds = Decimal(cast(str, format_data["duration"]))
    duration_ms = int(
        (duration_seconds * 1_000).to_integral_value(rounding=ROUND_HALF_UP)
    )

    streams: list[StreamInfo] = []
    for item in stream_data:
        codec_type = item.get("codec_type")
        if codec_type not in (StreamType.AUDIO.value, StreamType.VIDEO.value):
            continue
        streams.append(
            StreamInfo(
                index=cast(int, item["index"]),
                stream_type=StreamType(cast(str, codec_type)),
                codec_name=cast(str, item["codec_name"]),
            )
        )

    return ProbeResult(duration_ms=duration_ms, streams=tuple(streams))


__all__ = ["Command", "ProbeResult", "build_ffprobe_command", "parse_ffprobe_json"]
