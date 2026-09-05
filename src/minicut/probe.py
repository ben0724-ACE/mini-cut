"""Build ffprobe requests without executing external processes."""

from pathlib import Path

Command = tuple[str, ...]


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


__all__ = ["Command", "build_ffprobe_command"]
