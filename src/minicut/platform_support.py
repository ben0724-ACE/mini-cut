"""Backend platform defaults and non-destructive process inspection."""

import ctypes
import os
import platform
import sys
from collections.abc import Callable
from ctypes import wintypes
from typing import Literal, cast


def supports_mlx() -> bool:
    return sys.platform == "darwin" and platform.machine().lower() in {
        "arm64",
        "aarch64",
    }


def default_transcription_provider() -> Literal["mlx", "whisper"]:
    return "mlx" if supports_mlx() else "whisper"


def default_transcription_model() -> str:
    return "large-v3-turbo" if supports_mlx() else "small"


def valid_windows_filename(filename: str) -> bool:
    if not filename or filename.endswith((".", " ")):
        return False
    if any(character in '<>:"/\\|?*' or ord(character) < 32 for character in filename):
        return False
    stem = filename.split(".", 1)[0].rstrip(" ").upper()
    reserved = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    reserved.update(
        f"{prefix}{number}" for prefix in ("COM", "LPT") for number in "123456789¹²³"
    )
    return stem not in reserved


def process_alive(pid: int) -> bool:
    """Inspect a PID without sending a signal on Windows."""
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if sys.platform == "win32":
        return _windows_process_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _windows_process_alive(pid: int) -> bool:
    # ctypes' Windows-only names are absent from the type stubs on Unix hosts.
    load_library = cast(Callable[..., ctypes.CDLL], getattr(ctypes, "WinDLL"))  # noqa: B009
    last_error = cast(Callable[[], int], getattr(ctypes, "get_last_error"))  # noqa: B009
    win_error = cast(Callable[[int], OSError], getattr(ctypes, "WinError"))  # noqa: B009
    kernel = load_library("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetExitCodeProcess.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.DWORD),
    )
    kernel.GetExitCodeProcess.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        error = last_error()
        if error == 87:  # ERROR_INVALID_PARAMETER: PID no longer exists.
            return False
        if error == 5:  # Access denied does not prove the process has exited.
            return True
        raise win_error(error)
    try:
        code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
            raise win_error(last_error())
        return code.value == 259  # STILL_ACTIVE
    finally:
        kernel.CloseHandle(handle)
