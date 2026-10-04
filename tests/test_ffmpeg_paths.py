from pathlib import Path, PureWindowsPath

import pytest

from minicut.ffmpeg_paths import ffmpeg_file


@pytest.mark.parametrize(
    "path,expected",
    [
        (r"C:\视频 空格\采访%20.mp4", "file:C:/视频 空格/采访%20.mp4"),
        (r"\\server\share\视频 空格.mp4", "file://server/share/视频 空格.mp4"),
    ],
)
def test_windows_drive_and_unc_preserve_literal_names(path: str, expected: str) -> None:
    assert ffmpeg_file(PureWindowsPath(path)) == expected


def test_host_path_preserves_unicode_spaces_and_percent(tmp_path: Path) -> None:
    path = tmp_path / "采访 空格%20.mp4"
    value = ffmpeg_file(path)
    assert "采访 空格%20.mp4" in value
    assert "%E9" not in value
    assert ffmpeg_file(Path("relative.mp4")) == ffmpeg_file(
        Path("relative.mp4").absolute()
    )


def test_invalid_paths_rejected() -> None:
    with pytest.raises(ValueError):
        ffmpeg_file(PureWindowsPath("relative.mp4"))
    with pytest.raises(ValueError):
        ffmpeg_file("bad\0.mp4")
    with pytest.raises(ValueError):
        ffmpeg_file("")
