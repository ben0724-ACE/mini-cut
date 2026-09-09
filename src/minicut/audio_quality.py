"""Measure and assess rendered audio continuity with FFmpeg."""

import re
import subprocess
from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction
from pathlib import Path

from minicut.errors import ProcessingError
from minicut.probe import ProcessRunner, run_process
from minicut.timeline_validation import ValidationSeverity

_SILENCE_DURATION = re.compile(r"silence_duration:\s*([0-9]+(?:\.[0-9]+)?)")
_PEAK_LEVEL = re.compile(r"Peak level dB:\s*(-?(?:[0-9]+(?:\.[0-9]+)?|inf))")


class AudioQualityCode(StrEnum):
    """Machine-readable rendered-media quality findings."""

    EXCESSIVE_SILENCE = "excessive_silence"
    CLIPPING_RISK = "clipping_risk"
    AV_DURATION_MISMATCH = "av_duration_mismatch"


@dataclass(frozen=True, slots=True)
class AudioQualityIssue:
    """One measured audio continuity warning or blocking error."""

    code: AudioQualityCode
    message: str
    severity: ValidationSeverity


@dataclass(frozen=True, slots=True)
class AudioContinuityMetrics:
    """Measurements used to assess one rendered media file."""

    audio_present: bool
    audio_duration_ms: int | None = None
    video_duration_ms: int | None = None
    silence_duration_ms: int = 0
    peak_dbfs: float | None = None

    def __post_init__(self) -> None:
        durations = (self.audio_duration_ms, self.video_duration_ms)
        if any(duration is not None and duration < 0 for duration in durations):
            raise ValueError("media duration must not be negative")
        if self.silence_duration_ms < 0:
            raise ValueError("silence duration must not be negative")
        if not self.audio_present and (
            self.audio_duration_ms is not None or self.peak_dbfs is not None
        ):
            raise ValueError("audio measurements require an audio track")


@dataclass(frozen=True, slots=True)
class AudioContinuityReport:
    """Measured metrics, tolerance, and all quality findings."""

    metrics: AudioContinuityMetrics
    max_av_delta_ms: int
    issues: tuple[AudioQualityIssue, ...] = ()

    @property
    def can_publish(self) -> bool:
        return not any(
            issue.severity is ValidationSeverity.ERROR for issue in self.issues
        )


def build_audio_analysis_command(
    source_path: str | Path,
    *,
    executable: str = "ffmpeg",
) -> tuple[str, ...]:
    """Build argv for silence and peak-level measurement without shell parsing."""
    if not executable.strip():
        raise ValueError("FFmpeg executable must not be blank")
    source_url = Path(source_path).absolute().as_uri()
    return (
        executable,
        "-nostdin",
        "-hide_banner",
        "-i",
        source_url,
        "-af",
        "silencedetect=noise=-50dB:d=0.5,astats=metadata=1:reset=0",
        "-f",
        "null",
        "-",
    )


def parse_audio_analysis(stderr: str) -> tuple[int, float | None]:
    """Return total detected silence milliseconds and maximum peak dBFS."""
    silence_ms = round(
        sum(float(match) for match in _SILENCE_DURATION.findall(stderr)) * 1_000
    )
    peaks = [float(match) for match in _PEAK_LEVEL.findall(stderr)]
    return silence_ms, max(peaks, default=None)


def measure_audio_continuity(
    source_path: str | Path,
    *,
    audio_duration_ms: int,
    video_duration_ms: int | None = None,
    runner: ProcessRunner = run_process,
    executable: str = "ffmpeg",
    timeout_seconds: float = 30.0,
) -> AudioContinuityMetrics:
    """Execute FFmpeg analysis and combine it with probed stream durations."""
    command = build_audio_analysis_command(source_path, executable=executable)
    try:
        result = runner(command, timeout_seconds)
    except FileNotFoundError as error:
        raise ProcessingError("FFmpeg executable is not available.") from error
    except subprocess.TimeoutExpired as error:
        raise ProcessingError("FFmpeg audio analysis timed out.") from error
    if result.return_code != 0:
        raise ProcessingError("FFmpeg could not analyze rendered audio.")
    silence_duration_ms, peak_dbfs = parse_audio_analysis(result.stderr)
    return AudioContinuityMetrics(
        audio_present=True,
        audio_duration_ms=audio_duration_ms,
        video_duration_ms=video_duration_ms,
        silence_duration_ms=silence_duration_ms,
        peak_dbfs=peak_dbfs,
    )


def assess_audio_continuity(
    metrics: AudioContinuityMetrics,
    *,
    frame_rate: str,
    silence_ratio_threshold: float = 0.95,
    clipping_peak_dbfs: float = -0.1,
) -> AudioContinuityReport:
    """Classify silence, clipping, and A/V duration mismatch from measurements."""
    try:
        parsed_frame_rate = Fraction(frame_rate)
    except (ValueError, ZeroDivisionError) as error:
        raise ValueError("frame rate must be valid") from error
    if parsed_frame_rate <= 0:
        raise ValueError("frame rate must be positive")
    if not 0 < silence_ratio_threshold <= 1:
        raise ValueError("silence ratio threshold must be in (0, 1]")
    max_av_delta_ms = max(round(1_000 / float(parsed_frame_rate)), 40)
    issues: list[AudioQualityIssue] = []
    if not metrics.audio_present:
        return AudioContinuityReport(metrics, max_av_delta_ms)

    if (
        metrics.audio_duration_ms
        and metrics.silence_duration_ms / metrics.audio_duration_ms
        >= silence_ratio_threshold
    ):
        issues.append(
            AudioQualityIssue(
                AudioQualityCode.EXCESSIVE_SILENCE,
                "Rendered audio is almost entirely silent.",
                ValidationSeverity.WARNING,
            )
        )
    if metrics.peak_dbfs is not None and metrics.peak_dbfs >= clipping_peak_dbfs:
        issues.append(
            AudioQualityIssue(
                AudioQualityCode.CLIPPING_RISK,
                "Rendered audio peak is close to 0 dBFS and may clip.",
                ValidationSeverity.WARNING,
            )
        )
    if (
        metrics.audio_duration_ms is not None
        and metrics.video_duration_ms is not None
        and abs(metrics.audio_duration_ms - metrics.video_duration_ms) > max_av_delta_ms
    ):
        issues.append(
            AudioQualityIssue(
                AudioQualityCode.AV_DURATION_MISMATCH,
                "Rendered audio and video durations exceed the allowed difference.",
                ValidationSeverity.ERROR,
            )
        )
    return AudioContinuityReport(metrics, max_av_delta_ms, tuple(issues))


__all__ = [
    "AudioContinuityMetrics",
    "AudioContinuityReport",
    "AudioQualityCode",
    "AudioQualityIssue",
    "assess_audio_continuity",
    "build_audio_analysis_command",
    "measure_audio_continuity",
    "parse_audio_analysis",
]
