"""Pure, hand-verifiable metrics for reference edit selections."""

from collections.abc import Mapping
from dataclasses import dataclass

from minicut.eval_sample import EvalSample, ReferenceAction


@dataclass(frozen=True, slots=True)
class EvalClip:
    """One predicted source range and the kept Segments it covers."""

    source_start_ms: int
    source_end_ms: int
    segment_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.source_start_ms < 0 or self.source_end_ms <= self.source_start_ms:
            raise ValueError("evaluation clip source range is invalid")
        if not self.segment_ids or len(set(self.segment_ids)) != len(self.segment_ids):
            raise ValueError("evaluation clip Segment IDs must be non-empty and unique")


@dataclass(frozen=True, slots=True)
class EvalPrediction:
    """Planner actions and compiled duration for one evaluation sample."""

    actions: Mapping[str, ReferenceAction]
    estimated_duration_ms: int
    clips: tuple[EvalClip, ...] = ()

    def __post_init__(self) -> None:
        if self.estimated_duration_ms < 0:
            raise ValueError("predicted duration must not be negative")


@dataclass(frozen=True, slots=True)
class SelectionMetrics:
    """Selection quality counts, rates, and absolute/relative duration error."""

    reference_kept_segments: int
    correctly_kept_segments: int
    retention_recall: float
    predicted_deleted_segments: int
    correctly_deleted_segments: int
    deletion_accuracy: float
    reference_duration_ms: int
    predicted_duration_ms: int
    duration_error_ms: int
    duration_error_ratio: float


@dataclass(frozen=True, slots=True)
class TimelineQualityMetrics:
    """Counts and rates for boundary, isolation, and narrative defects."""

    clip_count: int
    cut_boundary_count: int
    cut_word_boundaries: int
    cut_word_rate: float
    isolated_clip_count: int
    isolated_clip_rate: float
    required_context_relationships: int
    narrative_break_count: int
    narrative_break_rate: float


def _validate_prediction_segments(
    sample: EvalSample, prediction: EvalPrediction
) -> dict[str, ReferenceAction]:
    reference_actions = {
        segment.segment_id: segment.reference_action for segment in sample.segments
    }
    if set(prediction.actions) != set(reference_actions):
        raise ValueError("prediction must contain exactly every reference Segment ID")
    return reference_actions


def _reference_duration_ms(sample: EvalSample) -> int:
    words = {word.word_id: word for word in sample.words}
    return sum(
        max(words[word_id].end_ms for word_id in segment.word_ids)
        - min(words[word_id].start_ms for word_id in segment.word_ids)
        for segment in sample.segments
        if segment.reference_action is ReferenceAction.KEEP
    )


def evaluate_selection(
    sample: EvalSample,
    prediction: EvalPrediction,
) -> SelectionMetrics:
    """Compare one prediction with the complete human reference selection."""
    reference_actions = _validate_prediction_segments(sample, prediction)

    reference_kept = sum(
        action is ReferenceAction.KEEP for action in reference_actions.values()
    )
    correctly_kept = sum(
        reference_actions[segment_id] is ReferenceAction.KEEP
        and action is ReferenceAction.KEEP
        for segment_id, action in prediction.actions.items()
    )
    predicted_deleted = sum(
        action is ReferenceAction.DELETE for action in prediction.actions.values()
    )
    correctly_deleted = sum(
        reference_actions[segment_id] is ReferenceAction.DELETE
        and action is ReferenceAction.DELETE
        for segment_id, action in prediction.actions.items()
    )

    retention_recall = correctly_kept / reference_kept if reference_kept else 1.0
    deletion_accuracy = (
        correctly_deleted / predicted_deleted if predicted_deleted else 1.0
    )
    reference_duration = _reference_duration_ms(sample)
    duration_error = abs(prediction.estimated_duration_ms - reference_duration)
    duration_error_ratio = (
        duration_error / reference_duration
        if reference_duration
        else float(duration_error > 0)
    )
    return SelectionMetrics(
        reference_kept,
        correctly_kept,
        retention_recall,
        predicted_deleted,
        correctly_deleted,
        deletion_accuracy,
        reference_duration,
        prediction.estimated_duration_ms,
        duration_error,
        duration_error_ratio,
    )


def evaluate_timeline_quality(
    sample: EvalSample,
    prediction: EvalPrediction,
    *,
    isolated_clip_threshold_ms: int = 300,
) -> TimelineQualityMetrics:
    """Measure defects in predicted clip boundaries and narrative continuity."""
    if isolated_clip_threshold_ms <= 0:
        raise ValueError("isolated clip threshold must be positive")
    _validate_prediction_segments(sample, prediction)
    predicted_kept = {
        segment_id
        for segment_id, action in prediction.actions.items()
        if action is ReferenceAction.KEEP
    }
    covered_segments = tuple(
        segment_id for clip in prediction.clips for segment_id in clip.segment_ids
    )
    if (
        len(set(covered_segments)) != len(covered_segments)
        or set(covered_segments) != predicted_kept
    ):
        raise ValueError(
            "evaluation clips must cover every predicted kept Segment once"
        )

    previous_end = 0
    for index, clip in enumerate(prediction.clips):
        if index and clip.source_start_ms < previous_end:
            raise ValueError(
                "evaluation clips must be source ordered and non-overlapping"
            )
        previous_end = clip.source_end_ms

    boundaries = tuple(
        boundary
        for clip in prediction.clips
        for boundary in (clip.source_start_ms, clip.source_end_ms)
    )
    cut_words = sum(
        any(word.start_ms < boundary < word.end_ms for word in sample.words)
        for boundary in boundaries
    )
    isolated = sum(
        clip.source_end_ms - clip.source_start_ms < isolated_clip_threshold_ms
        for clip in prediction.clips
    )
    context_relationships = tuple(
        context_id
        for segment in sample.segments
        if prediction.actions[segment.segment_id] is ReferenceAction.KEEP
        for context_id in segment.required_context_ids
    )
    narrative_breaks = sum(
        prediction.actions[context_id] is ReferenceAction.DELETE
        for context_id in context_relationships
    )
    boundary_count = len(boundaries)
    clip_count = len(prediction.clips)
    context_count = len(context_relationships)
    return TimelineQualityMetrics(
        clip_count,
        boundary_count,
        cut_words,
        cut_words / boundary_count if boundary_count else 0.0,
        isolated,
        isolated / clip_count if clip_count else 0.0,
        context_count,
        narrative_breaks,
        narrative_breaks / context_count if context_count else 0.0,
    )


__all__ = [
    "EvalClip",
    "EvalPrediction",
    "SelectionMetrics",
    "TimelineQualityMetrics",
    "evaluate_selection",
    "evaluate_timeline_quality",
]
