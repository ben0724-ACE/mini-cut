import asyncio
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from minicut import platform_support
from minicut.api import create_app
from minicut.platform_support import process_alive
from minicut.workflows import WorkflowTranscription


@pytest.mark.parametrize(
    "system,machine,provider,model",
    [
        ("win32", "AMD64", "whisper", "small"),
        ("linux", "x86_64", "whisper", "small"),
        ("darwin", "x86_64", "whisper", "small"),
        ("darwin", "arm64", "mlx", "large-v3-turbo"),
    ],
)
def test_defaults_follow_backend_and_preserve_explicit_configuration(
    tmp_path: Path, system: str, machine: str, provider: str, model: str
) -> None:
    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(tmp_path)),
            base_url="http://test",
        ) as client:
            response = await client.get("/api/transcription-defaults")
            assert response.status_code == 200
            assert response.json() == {
                "options": {"provider": provider, "model": model, "language": "zh"},
                "mlx_supported": provider == "mlx",
            }

    with (
        patch.object(platform_support.sys, "platform", system),
        patch.object(platform_support.platform, "machine", return_value=machine),
    ):
        asyncio.run(run())
        assert WorkflowTranscription().provider == provider
        assert WorkflowTranscription().model == model
        saved = WorkflowTranscription(provider="mlx", model="tiny", language="en")
        assert saved.provider == "mlx" and saved.model == "tiny"


def test_process_inspection_does_not_signal_current_process() -> None:
    with patch.object(platform_support.os, "kill", side_effect=AssertionError):
        assert process_alive(os.getpid())
        assert not process_alive(0)
        assert not process_alive(-1)


def test_child_process_liveness_before_and_after_exit() -> None:
    # On Windows this exercises OpenProcess/GetExitCodeProcess with a real child.
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert process_alive(child.pid)
    finally:
        child.terminate()
        child.wait(timeout=5)
    assert not process_alive(child.pid)


def test_windows_inspection_never_uses_kill() -> None:
    with (
        patch.object(platform_support.sys, "platform", "win32"),
        patch.object(platform_support, "_windows_process_alive", return_value=True),
        patch.object(platform_support.os, "kill", side_effect=AssertionError),
    ):
        assert process_alive(os.getpid() + 1)


@pytest.mark.parametrize(
    "name", ["CON.mp4", "nul.wav", "LPT1.mp4", "COM¹.mp4", "bad:video.mp4", "a.mp4."]
)
def test_windows_reserved_names_rejected(name: str) -> None:
    assert not platform_support.valid_windows_filename(name)
    assert platform_support.valid_windows_filename("中文 空格%20 [片段]'s.mp4")
