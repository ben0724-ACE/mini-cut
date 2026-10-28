from pathlib import Path

import pytest

import minicut.ffmpeg_runtime as runtime


@pytest.fixture
def homebrew(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("MINICUT_FFMPEG", raising=False)
    monkeypatch.setattr(runtime.sys, "platform", "darwin")
    monkeypatch.setattr(runtime, "_HOMEBREW_PREFIXES", (tmp_path,))

    def which(command: str) -> str:
        return str(tmp_path / "bin/ffmpeg")

    monkeypatch.setattr(runtime.shutil, "which", which)
    full = tmp_path / "opt/ffmpeg-full/bin/ffmpeg"
    full.parent.mkdir(parents=True)
    full.write_text("fixture")
    full.chmod(0o755)
    return full


def test_standard_homebrew_path_uses_installed_full_build(
    homebrew: Path,
) -> None:
    assert runtime.ffmpeg_executable() == str(homebrew)


def test_explicit_configuration_and_command_are_preserved(
    homebrew: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured = str(homebrew.parent / "custom ffmpeg")
    monkeypatch.setenv("MINICUT_FFMPEG", configured)
    assert runtime.ffmpeg_executable() == configured
    assert runtime.ffmpeg_executable("/another/ffmpeg") == "/another/ffmpeg"
    # An invalid explicit configuration must fail at launch, not silently switch.
    monkeypatch.setenv("MINICUT_FFMPEG", "/missing/ffmpeg")
    assert runtime.ffmpeg_executable() == "/missing/ffmpeg"


def test_custom_path_binary_is_not_replaced(
    homebrew: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def which(command: str) -> str:
        return "/custom/bin/ffmpeg"

    monkeypatch.setattr(runtime.shutil, "which", which)
    assert runtime.ffmpeg_executable() == "ffmpeg"


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_other_platforms_keep_path_or_explicit_configuration(
    homebrew: Path, monkeypatch: pytest.MonkeyPatch, platform: str
) -> None:
    monkeypatch.setattr(runtime.sys, "platform", platform)
    assert runtime.ffmpeg_executable() == "ffmpeg"
    monkeypatch.setenv("MINICUT_FFMPEG", str(homebrew))
    assert runtime.ffmpeg_executable() == str(homebrew)


def test_missing_full_build_keeps_path(homebrew: Path) -> None:
    homebrew.unlink()
    assert runtime.ffmpeg_executable() == "ffmpeg"
