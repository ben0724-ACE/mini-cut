"""Pure, hand-verifiable metrics for reference edit selections."""

from collections.abc import Mapping
from dataclasses import dataclass

from minicut.eval_sample import EvalSample, ReferenceAction


@dataclass(frozen=True, slots=True)
class EvalPrediction:
    """Planner actions and compiled duration for one evaluation sample."""

    actions: Mapping[str, ReferenceAction]
    estimated_duration_ms: int

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
    reference_actions = {
        segment.segment_id: segment.reference_action for segment in sample.segments
    }
    if set(prediction.actions) != set(reference_actions):
        raise ValueError("prediction must contain exactly every reference Segment ID")

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


__all__ = ["EvalPrediction", "SelectionMetrics", "evaluate_selection"]
