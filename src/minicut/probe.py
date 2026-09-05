"""Build ffprobe requests and parse their JSON output."""

import json
import subprocess
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Protocol, cast

from minicut.errors import ProcessingError, UserInputError
from minicut.media import StreamInfo, StreamType

Command = tuple[str, ...]


@dataclass(slots=True)
class ProcessResult:
    """Captured output from one external process invocation."""

    return_code: int
    stdout: str
    stderr: str


class ProcessRunner(Protocol):
    """Callable boundary used to replace external process execution in tests."""

    def __call__(self, command: Command, timeout_seconds: float) -> ProcessResult:
        """Run a command and return captured output."""
        ...


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


def run_process(command: Command, timeout_seconds: float) -> ProcessResult:
    """Execute a command and capture its text output."""
    completed = subprocess.run(
        command,
        capture_output=True,
        check=False,
        text=True,
        timeout=timeout_seconds,
    )
    return ProcessResult(
        return_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def probe_media(
    source_path: str | Path,
    *,
    runner: ProcessRunner = run_process,
    executable: str = "ffprobe",
    timeout_seconds: float = 30.0,
) -> ProbeResult:
    """Run ffprobe and map its expected failures to safe domain errors."""
    command = build_ffprobe_command(source_path, executable=executable)
    try:
        process_result = runner(command, timeout_seconds)
    except FileNotFoundError as error:
        raise ProcessingError("ffprobe executable is not available.") from error
    except subprocess.TimeoutExpired as error:
        raise ProcessingError(
            "ffprobe timed out while reading the media file."
        ) from error

    if process_result.return_code != 0:
        raise ProcessingError("ffprobe could not read the media file.")

    try:
        result = parse_ffprobe_json(process_result.stdout)
    except (ArithmeticError, AttributeError, KeyError, TypeError, ValueError) as error:
        raise ProcessingError("ffprobe returned invalid metadata.") from error

    if not result.streams:
        raise UserInputError("Media contains no supported audio or video streams.")
    return result


__all__ = [
    "Command",
    "ProbeResult",
    "ProcessResult",
    "ProcessRunner",
    "build_ffprobe_command",
    "parse_ffprobe_json",
    "probe_media",
    "run_process",
]
