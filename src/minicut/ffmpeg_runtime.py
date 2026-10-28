"""Resolve the render runtime without depending on a shell's temporary PATH."""

import os
import shutil
import sys
from pathlib import Path

_HOMEBREW_PREFIXES = (Path("/opt/homebrew"), Path("/usr/local"))


def ffmpeg_executable(requested: str = "ffmpeg") -> str:
    """Honor explicit binaries; prefer Homebrew full over its default build."""
    if requested != "ffmpeg":
        return requested
    configured = os.environ.get("MINICUT_FFMPEG", "").strip()
    if configured:
        return str(Path(configured).expanduser())
    if sys.platform == "darwin":
        found = shutil.which("ffmpeg")
        for prefix in _HOMEBREW_PREFIXES:
            full = prefix / "opt/ffmpeg-full/bin/ffmpeg"
            if (
                found in {None, str(prefix / "bin/ffmpeg")}
                and full.is_file()
                and os.access(full, os.X_OK)
            ):
                return str(full)
    return requested
