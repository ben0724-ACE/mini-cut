"""Independent validation for timelines at the pre-render boundary."""

from dataclasses import dataclass
from enum import StrEnum

from minicut.media import MediaAsset, StreamType
from minicut.timeline import Clip, Timeline


class ValidationSeverity(StrEnum):
    """Whether a validation issue blocks rendering."""

    ERROR = "error"
    WARNING = "warning"


class TimelineValidationCode(StrEnum):
    """Machine-readable structural timeline failures."""

    EMPTY_TIMELINE = "empty_timeline"
    DUPLICATE_CLIP_ID = "duplicate_clip_id"
    DUPLICATE_ASSET_ID = "duplicate_asset_id"
    UNKNOWN_ASSET = "unknown_asset"
    SOURCE_OUT_OF_RANGE = "source_out_of_range"
    SOURCE_ORDER = "source_order"
    SOURCE_OVERLAP = "source_overlap"
    OUTPUT_DISCONTINUITY = "output_discontinuity"
    OUTPUT_DURATION_MISMATCH = "output_duration_mismatch"
    DURATION_MISMATCH = "duration_mismatch"
    MISSING_AUDIO_TRACK = "missing_audio_track"
    MISSING_VIDEO_TRACK = "missing_video_track"


@dataclass(frozen=True, slots=True)
class TimelineTrackRequirements:
    """Stream types required from every media asset used by a timeline."""

    require_audio: bool = False
    require_video: bool = False

    def __post_init__(self) -> None:
        if not self.require_audio and not self.require_video:
            raise ValueError("at least one timeline track type must be required")


@dataclass(frozen=True, slots=True)
class TimelineValidationIssue:
    """One structural error or non-blocking warning."""

    code: TimelineValidationCode
    message: str
    clip_ids: tuple[str, ...] = ()
    severity: ValidationSeverity = ValidationSeverity.ERROR

    def __post_init__(self) -> None:
        if not self.message.strip():
            raise ValueError("timeline validation message must not be blank")


class TimelineValidationError(ValueError):
    """Hard validation failure that must block rendering."""

    def __init__(self, issues: tuple[TimelineValidationIssue, ...]) -> None:
        self.issues = issues
        super().__init__(f"timeline has {len(issues)} blocking validation issue(s)")


def _issue(
    code: TimelineValidationCode,
    message: str,
    *clips: Clip,
) -> TimelineValidationIssue:
    return TimelineValidationIssue(
        code,
        message,
        tuple(clip.clip_id for clip in clips),
    )


def inspect_timeline_structure(
    timeline: Timeline,
    assets: tuple[MediaAsset, ...],
) -> tuple[TimelineValidationIssue, ...]:
    """Return every structural issue without changing the timeline."""
    issues: list[TimelineValidationIssue] = []
    assets_by_id = {asset.asset_id: asset for asset in assets}
    if len(assets_by_id) != len(assets):
        issues.append(
            _issue(
                TimelineValidationCode.DUPLICATE_ASSET_ID,
                "Media asset IDs must be unique.",
            )
        )
    if not timeline.clips:
        issues.append(
            _issue(
                TimelineValidationCode.EMPTY_TIMELINE,
                "Timeline must contain at least one clip.",
            )
        )

    clip_ids = tuple(clip.clip_id for clip in timeline.clips)
    if len(set(clip_ids)) != len(clip_ids):
        issues.append(
            _issue(
                TimelineValidationCode.DUPLICATE_CLIP_ID,
                "Timeline clip IDs must be unique.",
            )
        )

    previous_by_asset: dict[str, Clip] = {}
    output_cursor_ms = 0
    for clip in timeline.clips:
        asset = assets_by_id.get(clip.source_asset_id)
        if asset is None:
            issues.append(
                _issue(
                    TimelineValidationCode.UNKNOWN_ASSET,
                    "Clip references an unknown media asset.",
                    clip,
                )
            )
        elif clip.source_range.end_ms > asset.duration_ms:
            issues.append(
                _issue(
                    TimelineValidationCode.SOURCE_OUT_OF_RANGE,
                    "Clip source range exceeds its media duration.",
                    clip,
                )
            )

        previous = previous_by_asset.get(clip.source_asset_id)
        if previous is not None:
            if clip.source_range.start_ms < previous.source_range.start_ms:
                issues.append(
                    _issue(
                        TimelineValidationCode.SOURCE_ORDER,
                        "Same-asset clips are not in source time order.",
                        previous,
                        clip,
                    )
                )
            elif clip.source_range.start_ms < previous.source_range.end_ms:
                issues.append(
                    _issue(
                        TimelineValidationCode.SOURCE_OVERLAP,
                        "Same-asset clip source ranges overlap.",
                        previous,
                        clip,
                    )
                )
        previous_by_asset[clip.source_asset_id] = clip

        if clip.output_range.start_ms != output_cursor_ms:
            issues.append(
                _issue(
                    TimelineValidationCode.OUTPUT_DISCONTINUITY,
                    "Clip output ranges must be contiguous from zero.",
                    clip,
                )
            )
        if clip.output_range.duration_ms != clip.source_range.duration_ms:
            issues.append(
                _issue(
                    TimelineValidationCode.OUTPUT_DURATION_MISMATCH,
                    "Clip source and output durations must match.",
                    clip,
                )
            )
        output_cursor_ms = clip.output_range.end_ms

    if timeline.estimated_duration_ms != output_cursor_ms:
        issues.append(
            _issue(
                TimelineValidationCode.DURATION_MISMATCH,
                "Timeline duration must equal the final output end.",
            )
        )
    return tuple(issues)


def validate_timeline_structure(
    timeline: Timeline,
    assets: tuple[MediaAsset, ...],
) -> None:
    """Raise when any structural issue would make rendering unsafe."""
    issues = inspect_timeline_structure(timeline, assets)
    blocking = tuple(
        issue for issue in issues if issue.severity is ValidationSeverity.ERROR
    )
    if blocking:
        raise TimelineValidationError(blocking)


def inspect_timeline_tracks(
    timeline: Timeline,
    assets: tuple[MediaAsset, ...],
    requirements: TimelineTrackRequirements,
) -> tuple[TimelineValidationIssue, ...]:
    """Return missing required streams for each referenced source asset."""
    assets_by_id = {asset.asset_id: asset for asset in assets}
    referenced_asset_ids = tuple(
        dict.fromkeys(clip.source_asset_id for clip in timeline.clips)
    )
    issues: list[TimelineValidationIssue] = []
    for asset_id in referenced_asset_ids:
        asset = assets_by_id.get(asset_id)
        matching_clips = tuple(
            clip for clip in timeline.clips if clip.source_asset_id == asset_id
        )
        if asset is None:
            issues.append(
                _issue(
                    TimelineValidationCode.UNKNOWN_ASSET,
                    "Clip references an unknown media asset.",
                    *matching_clips,
                )
            )
            continue
        stream_types = {stream.stream_type for stream in asset.streams}
        if requirements.require_audio and StreamType.AUDIO not in stream_types:
            issues.append(
                _issue(
                    TimelineValidationCode.MISSING_AUDIO_TRACK,
                    "Referenced media asset has no required audio track.",
                    *matching_clips,
                )
            )
        if requirements.require_video and StreamType.VIDEO not in stream_types:
            issues.append(
                _issue(
                    TimelineValidationCode.MISSING_VIDEO_TRACK,
                    "Referenced media asset has no required video track.",
                    *matching_clips,
                )
            )
    return tuple(issues)


def validate_timeline_tracks(
    timeline: Timeline,
    assets: tuple[MediaAsset, ...],
    requirements: TimelineTrackRequirements,
) -> None:
    """Block rendering when a referenced asset lacks a required stream type."""
    issues = inspect_timeline_tracks(timeline, assets, requirements)
    blocking = tuple(
        issue for issue in issues if issue.severity is ValidationSeverity.ERROR
    )
    if blocking:
        raise TimelineValidationError(blocking)


__all__ = [
    "TimelineValidationCode",
    "TimelineValidationError",
    "TimelineValidationIssue",
    "TimelineTrackRequirements",
    "ValidationSeverity",
    "inspect_timeline_tracks",
    "inspect_timeline_structure",
    "validate_timeline_tracks",
    "validate_timeline_structure",
]
