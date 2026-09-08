"""Deterministic timeline merging and naturalness analysis."""

from dataclasses import dataclass
from enum import StrEnum

from minicut.media import TimeRange
from minicut.timeline import Clip, Timeline


class TimelineAdjustmentReason(StrEnum):
    """Machine-readable reasons for timeline repairs."""

    NEARBY_MERGE = "nearby_merge"
    SHORT_CLIP_REMOVAL = "short_clip_removal"


class TimelineRiskReason(StrEnum):
    """Machine-readable reasons for non-mutating timeline risks."""

    SOURCE_GAP = "source_gap"


@dataclass(frozen=True, slots=True)
class TimelineAdjustment:
    """One traceable transformation from input clips to an output clip."""

    reason: TimelineAdjustmentReason
    input_clip_ids: tuple[str, ...]
    output_clip_id: str | None
    explanation: str

    def __post_init__(self) -> None:
        if not self.input_clip_ids:
            raise ValueError("timeline adjustment requires an input clip")
        if any(not clip_id.strip() for clip_id in self.input_clip_ids):
            raise ValueError("timeline adjustment clip IDs must not be blank")
        if self.reason is TimelineAdjustmentReason.NEARBY_MERGE:
            if len(self.input_clip_ids) < 2 or not self.output_clip_id:
                raise ValueError("nearby merge requires inputs and an output clip")
        elif len(self.input_clip_ids) != 1 or self.output_clip_id is not None:
            raise ValueError("short clip removal must have one input and no output")
        if not self.explanation.strip():
            raise ValueError("timeline adjustment explanation must not be blank")


@dataclass(frozen=True, slots=True)
class TimelineTransformResult:
    """A transformed timeline plus every applied machine-readable adjustment."""

    timeline: Timeline
    adjustments: tuple[TimelineAdjustment, ...] = ()


@dataclass(frozen=True, slots=True)
class JumpCutRisk:
    """A source discontinuity that may be visible at an output junction."""

    reason: TimelineRiskReason
    left_clip_id: str
    right_clip_id: str
    removed_gap_ms: int
    output_at_ms: int
    explanation: str

    def __post_init__(self) -> None:
        if not self.left_clip_id.strip() or not self.right_clip_id.strip():
            raise ValueError("jump-cut risk clip IDs must not be blank")
        if self.removed_gap_ms <= 0:
            raise ValueError("jump-cut risk source gap must be positive")
        if self.output_at_ms < 0:
            raise ValueError("jump-cut risk output time must not be negative")
        if not self.explanation.strip():
            raise ValueError("jump-cut risk explanation must not be blank")


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


def handle_short_isolated_clips(
    timeline: Timeline,
    min_duration_ms: int,
    protected_segment_ids: tuple[str, ...] = (),
) -> TimelineTransformResult:
    """Remove unprotected short clips while always keeping a non-empty timeline."""
    if min_duration_ms <= 0:
        raise ValueError("minimum clip duration must be positive")
    covered_ids = {
        segment_id for clip in timeline.clips for segment_id in clip.segment_ids
    }
    protected_ids = set(protected_segment_ids)
    if not protected_ids <= covered_ids:
        raise ValueError("protected Segment is missing from the timeline")

    removable_ids = {
        clip.clip_id
        for clip in timeline.clips
        if clip.source_range.duration_ms < min_duration_ms
        and not protected_ids.intersection(clip.segment_ids)
    }
    if removable_ids and len(removable_ids) == len(timeline.clips):
        retained = max(
            timeline.clips,
            key=lambda clip: clip.source_range.duration_ms,
        )
        removable_ids.remove(retained.clip_id)
    if not removable_ids:
        return TimelineTransformResult(timeline)

    kept_clips = tuple(
        clip for clip in timeline.clips if clip.clip_id not in removable_ids
    )
    adjustments = tuple(
        TimelineAdjustment(
            TimelineAdjustmentReason.SHORT_CLIP_REMOVAL,
            (clip.clip_id,),
            None,
            (
                f"Removed an unprotected {clip.source_range.duration_ms} ms clip "
                f"below the {min_duration_ms} ms minimum."
            ),
        )
        for clip in timeline.clips
        if clip.clip_id in removable_ids
    )
    return TimelineTransformResult(_reflow(kept_clips), adjustments)


def detect_jump_cut_risks(
    timeline: Timeline,
    min_removed_gap_ms: int,
) -> tuple[JumpCutRisk, ...]:
    """Mark same-asset source gaps without mutating the timeline."""
    if min_removed_gap_ms <= 0:
        raise ValueError("jump-cut gap threshold must be positive")
    risks: list[JumpCutRisk] = []
    for left, right in zip(timeline.clips, timeline.clips[1:], strict=False):
        if left.source_asset_id != right.source_asset_id:
            continue
        removed_gap_ms = right.source_range.start_ms - left.source_range.end_ms
        if removed_gap_ms < min_removed_gap_ms:
            continue
        risks.append(
            JumpCutRisk(
                TimelineRiskReason.SOURCE_GAP,
                left.clip_id,
                right.clip_id,
                removed_gap_ms,
                right.output_range.start_ms,
                (
                    f"The output junction skips {removed_gap_ms} ms of the same "
                    "source and may produce a visible jump cut."
                ),
            )
        )
    return tuple(risks)


__all__ = [
    "JumpCutRisk",
    "TimelineAdjustment",
    "TimelineAdjustmentReason",
    "TimelineTransformResult",
    "TimelineRiskReason",
    "detect_jump_cut_risks",
    "handle_short_isolated_clips",
    "merge_nearby_clips",
]
