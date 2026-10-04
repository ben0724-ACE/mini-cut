"""Local FFmpeg filenames: preserve Unicode and literal percent characters."""

from pathlib import Path, PurePath, PureWindowsPath


def ffmpeg_file(path: str | PurePath) -> str:
    if not str(path) or "\0" in str(path):
        raise ValueError("FFmpeg requires a valid local path")
    local = (
        path
        if isinstance(path, PureWindowsPath) and not isinstance(path, Path)
        else Path(path).absolute()
    )
    if not str(local) or "\0" in str(local) or not local.is_absolute():
        raise ValueError("FFmpeg requires a valid absolute local path")
    # A Windows file URI adds slashes before the drive, which FFmpeg passes to
    # the filesystem. Use file:C:/... (or file://server/share/... for UNC).
    if isinstance(local, PureWindowsPath):
        return "file:" + local.as_posix()
    return "file://" + local.as_posix()
