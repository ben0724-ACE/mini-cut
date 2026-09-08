"""Deterministic timeline merging and naturalness analysis."""

from dataclasses import dataclass
from enum import StrEnum

from minicut.media import TimeRange
from minicut.timeline import Clip, Timeline


class TimelineAdjustmentReason(StrEnum):
    """Machine-readable reasons for timeline repairs."""

    NEARBY_MERGE = "nearby_merge"


@dataclass(frozen=True, slots=True)
class TimelineAdjustment:
    """One traceable transformation from input clips to an output clip."""

    reason: TimelineAdjustmentReason
    input_clip_ids: tuple[str, ...]
    output_clip_id: str
    explanation: str

    def __post_init__(self) -> None:
        if len(self.input_clip_ids) < 2:
            raise ValueError("timeline adjustment requires at least two input clips")
        if any(not clip_id.strip() for clip_id in self.input_clip_ids):
            raise ValueError("timeline adjustment clip IDs must not be blank")
        if not self.output_clip_id.strip():
            raise ValueError("timeline adjustment output clip ID must not be blank")
        if not self.explanation.strip():
            raise ValueError("timeline adjustment explanation must not be blank")


@dataclass(frozen=True, slots=True)
class TimelineTransformResult:
    """A transformed timeline plus every applied machine-readable adjustment."""

    timeline: Timeline
    adjustments: tuple[TimelineAdjustment, ...] = ()


def _reflow(clips: tuple[Clip, ...]) -> Timeline:
    output_cursor_ms = 0
    reflowed: list[Clip] = []
    for clip in clips:
        output_end_ms = output_cursor_ms + clip.source_range.duration_ms
        reflowed.append(
            Clip(
                clip.clip_id,
                clip.source_asset_id,
                clip.segment_id,
                clip.source_range,
                TimeRange(output_cursor_ms, output_end_ms),
                clip.segment_ids,
            )
        )
        output_cursor_ms = output_end_ms
    return Timeline(tuple(reflowed), output_cursor_ms)


def _combined_segment_ids(left: Clip, right: Clip) -> tuple[str, ...]:
    return tuple(dict.fromkeys((*left.segment_ids, *right.segment_ids)))


def merge_nearby_clips(
    timeline: Timeline,
    max_gap_ms: int,
) -> TimelineTransformResult:
    """Merge same-asset clips separated by less than the configured gap."""
    if max_gap_ms < 0:
        raise ValueError("merge gap threshold must not be negative")
    if not timeline.clips:
        return TimelineTransformResult(timeline)

    merged: list[Clip] = [timeline.clips[0]]
    adjustments: list[TimelineAdjustment] = []
    for current in timeline.clips[1:]:
        previous = merged[-1]
        same_asset = previous.source_asset_id == current.source_asset_id
        gap_ms = current.source_range.start_ms - previous.source_range.end_ms
        if same_asset and gap_ms < 0:
            raise ValueError("timeline source clips overlap before merging")
        if not same_asset or gap_ms >= max_gap_ms:
            merged.append(current)
            continue

        output_clip = Clip(
            previous.clip_id,
            previous.source_asset_id,
            previous.segment_id,
            TimeRange(previous.source_range.start_ms, current.source_range.end_ms),
            previous.output_range,
            _combined_segment_ids(previous, current),
        )
        merged[-1] = output_clip
        adjustments.append(
            TimelineAdjustment(
                TimelineAdjustmentReason.NEARBY_MERGE,
                (previous.clip_id, current.clip_id),
                output_clip.clip_id,
                f"Merged clips across a {gap_ms} ms source gap.",
            )
        )
    return TimelineTransformResult(_reflow(tuple(merged)), tuple(adjustments))


__all__ = [
    "TimelineAdjustment",
    "TimelineAdjustmentReason",
    "TimelineTransformResult",
    "merge_nearby_clips",
]
