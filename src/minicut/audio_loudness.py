"""Two-pass EBU R128 loudness analysis and normalization commands."""

import json
import re
import subprocess
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import cast

from minicut.errors import ProcessingError
from minicut.probe import ProcessRunner, run_process


@dataclass(frozen=True, slots=True)
class LoudnessProfile:
    target_lufs: float = -16.0
    true_peak_dbfs: float = -1.5
    loudness_range_lu: float = 11.0
    tolerance_lu: float = 1.0

    def __post_init__(self) -> None:
        if not -70 <= self.target_lufs <= -5:
            raise ValueError("target loudness must be between -70 and -5 LUFS")
        if not -9 <= self.true_peak_dbfs <= 0:
            raise ValueError("true peak target must be between -9 and 0 dBFS")
        if not 1 <= self.loudness_range_lu <= 50:
            raise ValueError("loudness range target must be between 1 and 50 LU")
        if self.tolerance_lu <= 0:
            raise ValueError("loudness tolerance must be positive")


@dataclass(frozen=True, slots=True)
class LoudnessMeasurement:
    input_lufs: float
    input_true_peak_dbfs: float
    input_loudness_range_lu: float
    input_threshold_lufs: float
    target_offset_lu: float

    def __post_init__(self) -> None:
        if not all(
            isfinite(value)
            for value in (
                self.input_lufs,
                self.input_true_peak_dbfs,
                self.input_loudness_range_lu,
                self.input_threshold_lufs,
                self.target_offset_lu,
            )
        ):
            raise ValueError("loudness measurement values must be finite")


_DEFAULT_LOUDNESS_PROFILE = LoudnessProfile()


def _number(value: float) -> str:
    return f"{value:.1f}"


def _input_url(path: str | Path) -> str:
    return Path(path).absolute().as_uri()


def _analysis_filter(profile: LoudnessProfile) -> str:
    return (
        f"loudnorm=I={_number(profile.target_lufs)}:"
        f"LRA={_number(profile.loudness_range_lu)}:"
        f"TP={_number(profile.true_peak_dbfs)}:print_format=json"
    )


def build_loudness_analysis_command(
    source_path: str | Path,
    profile: LoudnessProfile = _DEFAULT_LOUDNESS_PROFILE,
    *,
    executable: str = "ffmpeg",
) -> tuple[str, ...]:
    if not executable.strip():
        raise ValueError("FFmpeg executable must not be blank")
    return (
        executable,
        "-nostdin",
        "-hide_banner",
        "-i",
        _input_url(source_path),
        "-af",
        _analysis_filter(profile),
        "-f",
        "null",
        "-",
    )


_MEASUREMENT_JSON = re.compile(r"\{[^{}]*\"input_i\"[^{}]*\}", re.DOTALL)


def parse_loudness_measurement(stderr: str) -> LoudnessMeasurement:
    match = _MEASUREMENT_JSON.search(stderr)
    if match is None:
        raise ValueError("FFmpeg loudness measurement JSON is missing")
    try:
        data = cast(dict[str, object], json.loads(match.group()))
        return LoudnessMeasurement(
            float(cast(str, data["input_i"])),
            float(cast(str, data["input_tp"])),
            float(cast(str, data["input_lra"])),
            float(cast(str, data["input_thresh"])),
            float(cast(str, data["target_offset"])),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("FFmpeg loudness measurement JSON is invalid") from error


def measure_loudness(
    source_path: str | Path,
    profile: LoudnessProfile = _DEFAULT_LOUDNESS_PROFILE,
    *,
    runner: ProcessRunner = run_process,
    executable: str = "ffmpeg",
    timeout_seconds: float = 30,
) -> LoudnessMeasurement:
    command = build_loudness_analysis_command(
        source_path, profile, executable=executable
    )
    try:
        result = runner(command, timeout_seconds)
    except FileNotFoundError as error:
        raise ProcessingError("FFmpeg executable is not available.") from error
    except subprocess.TimeoutExpired as error:
        raise ProcessingError("FFmpeg loudness analysis timed out.") from error
    if result.return_code != 0:
        raise ProcessingError("FFmpeg could not analyze audio loudness.")
    try:
        return parse_loudness_measurement(result.stderr)
    except ValueError as error:
        raise ProcessingError("FFmpeg returned invalid loudness data.") from error


def build_loudness_normalization_command(
    source_path: str | Path,
    output_path: str | Path,
    profile: LoudnessProfile,
    measurement: LoudnessMeasurement,
    *,
    executable: str = "ffmpeg",
) -> tuple[str, ...]:
    if not executable.strip():
        raise ValueError("FFmpeg executable must not be blank")
    loudnorm = (
        f"loudnorm=I={_number(profile.target_lufs)}:"
        f"LRA={_number(profile.loudness_range_lu)}:"
        f"TP={_number(profile.true_peak_dbfs)}:"
        f"measured_I={measurement.input_lufs}:"
        f"measured_LRA={measurement.input_loudness_range_lu}:"
        f"measured_TP={measurement.input_true_peak_dbfs}:"
        f"measured_thresh={measurement.input_threshold_lufs}:"
        f"offset={measurement.target_offset_lu}:linear=true:print_format=summary"
    )
    return (
        executable,
        "-nostdin",
        "-y",
        "-i",
        _input_url(source_path),
        "-map",
        "0:v?",
        "-map",
        "0:a:0",
        "-c:v",
        "copy",
        "-af",
        loudnorm,
        "-c:a",
        "aac",
        "-ar",
        "48000",
        _input_url(output_path),
    )


__all__ = [
    "LoudnessMeasurement",
    "LoudnessProfile",
    "build_loudness_analysis_command",
    "build_loudness_normalization_command",
    "measure_loudness",
    "parse_loudness_measurement",
]
