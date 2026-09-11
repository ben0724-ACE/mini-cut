"""Offline batch replay for anonymous edit-quality samples."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from minicut.eval_metrics import (
    EvalPrediction,
    SelectionMetrics,
    TimelineQualityMetrics,
    evaluate_selection,
    evaluate_timeline_quality,
)
from minicut.eval_sample import EvalSample, ReferenceAction

EvalReplay = Callable[[EvalSample], EvalPrediction]


@dataclass(frozen=True, slots=True)
class EvalCaseResult:
    sample_id: str
    prediction: EvalPrediction
    selection: SelectionMetrics
    timeline: TimelineQualityMetrics


@dataclass(frozen=True, slots=True)
class EvalRunResult:
    cases: tuple[EvalCaseResult, ...]


@dataclass(frozen=True, slots=True)
class QualityDelta:
    """Candidate minus baseline; error-rate improvements are negative values."""

    retention_recall_delta: float
    deletion_accuracy_delta: float
    duration_error_ratio_delta: float
    cut_word_rate_delta: float
    isolated_clip_rate_delta: float
    narrative_break_rate_delta: float


@dataclass(frozen=True, slots=True)
class DecisionChange:
    sample_id: str
    segment_id: str
    baseline_action: ReferenceAction
    candidate_action: ReferenceAction


@dataclass(frozen=True, slots=True)
class EvalCaseComparison:
    sample_id: str
    delta: QualityDelta
    decision_changes: tuple[DecisionChange, ...]


@dataclass(frozen=True, slots=True)
class EvalComparisonReport:
    sample_count: int
    aggregate: QualityDelta
    cases: tuple[EvalCaseComparison, ...]


@dataclass(frozen=True, slots=True)
class ReleaseQualityPolicy:
    """Maximum per-sample degradation allowed at the formal release boundary."""

    max_retention_recall_drop: float
    max_deletion_accuracy_drop: float
    max_duration_error_increase: float
    max_cut_word_rate_increase: float
    max_isolated_clip_rate_increase: float
    max_narrative_break_rate_increase: float

    def __post_init__(self) -> None:
        values = (
            self.max_retention_recall_drop,
            self.max_deletion_accuracy_drop,
            self.max_duration_error_increase,
            self.max_cut_word_rate_increase,
            self.max_isolated_clip_rate_increase,
            self.max_narrative_break_rate_increase,
        )
        if any(value < 0 for value in values):
            raise ValueError("release quality thresholds must not be negative")


@dataclass(frozen=True, slots=True)
class ReleaseQualityViolation:
    metric: str
    observed_degradation: float
    allowed_degradation: float
    worst_sample_id: str
    decision_changes: tuple[DecisionChange, ...]


@dataclass(frozen=True, slots=True)
class ReleaseQualityDecision:
    can_release: bool
    violations: tuple[ReleaseQualityViolation, ...]


def _read_sample(path: Path) -> EvalSample:
    try:
        payload = cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))
        return EvalSample.from_dict(payload)
    except (KeyError, OSError, TypeError, UnicodeError, ValueError) as error:
        raise ValueError(f"invalid evaluation sample: {path.name}") from error


def run_evaluation_directory(
    sample_directory: Path,
    replay: EvalReplay,
    *,
    isolated_clip_threshold_ms: int = 300,
) -> EvalRunResult:
    """Replay every JSON sample without invoking transcription or rendering."""
    if not sample_directory.is_dir():
        raise ValueError("evaluation sample directory does not exist")
    paths = tuple(sorted(sample_directory.glob("*.json"), key=lambda path: path.name))
    if not paths:
        raise ValueError("evaluation sample directory contains no JSON samples")
    samples = tuple(_read_sample(path) for path in paths)
    sample_ids = tuple(sample.sample_id for sample in samples)
    if len(set(sample_ids)) != len(sample_ids):
        raise ValueError("duplicate evaluation sample ID in batch")

    cases: list[EvalCaseResult] = []
    for sample in samples:
        prediction = replay(sample)
        cases.append(
            EvalCaseResult(
                sample.sample_id,
                prediction,
                evaluate_selection(sample, prediction),
                evaluate_timeline_quality(
                    sample,
                    prediction,
                    isolated_clip_threshold_ms=isolated_clip_threshold_ms,
                ),
            )
        )
    return EvalRunResult(tuple(cases))


def _quality_delta(
    baseline: EvalCaseResult,
    candidate: EvalCaseResult,
) -> QualityDelta:
    return QualityDelta(
        candidate.selection.retention_recall - baseline.selection.retention_recall,
        candidate.selection.deletion_accuracy - baseline.selection.deletion_accuracy,
        candidate.selection.duration_error_ratio
        - baseline.selection.duration_error_ratio,
        candidate.timeline.cut_word_rate - baseline.timeline.cut_word_rate,
        candidate.timeline.isolated_clip_rate - baseline.timeline.isolated_clip_rate,
        candidate.timeline.narrative_break_rate
        - baseline.timeline.narrative_break_rate,
    )


def _mean_delta(deltas: tuple[QualityDelta, ...]) -> QualityDelta:
    count = len(deltas)
    return QualityDelta(
        sum(delta.retention_recall_delta for delta in deltas) / count,
        sum(delta.deletion_accuracy_delta for delta in deltas) / count,
        sum(delta.duration_error_ratio_delta for delta in deltas) / count,
        sum(delta.cut_word_rate_delta for delta in deltas) / count,
        sum(delta.isolated_clip_rate_delta for delta in deltas) / count,
        sum(delta.narrative_break_rate_delta for delta in deltas) / count,
    )


def compare_eval_runs(
    baseline: EvalRunResult,
    candidate: EvalRunResult,
) -> EvalComparisonReport:
    """Compare two completed runs without freezing either run as a contract."""
    baseline_by_id = {case.sample_id: case for case in baseline.cases}
    candidate_by_id = {case.sample_id: case for case in candidate.cases}
    if (
        not baseline_by_id
        or len(baseline_by_id) != len(baseline.cases)
        or len(candidate_by_id) != len(candidate.cases)
        or set(baseline_by_id) != set(candidate_by_id)
    ):
        raise ValueError("evaluation runs must contain the same sample IDs once")

    comparisons: list[EvalCaseComparison] = []
    for baseline_case in baseline.cases:
        candidate_case = candidate_by_id[baseline_case.sample_id]
        segment_ids = sorted(baseline_case.prediction.actions)
        if set(segment_ids) != set(candidate_case.prediction.actions):
            raise ValueError("matching samples must contain the same Segment IDs")
        changes = tuple(
            DecisionChange(
                baseline_case.sample_id,
                segment_id,
                baseline_case.prediction.actions[segment_id],
                candidate_case.prediction.actions[segment_id],
            )
            for segment_id in segment_ids
            if baseline_case.prediction.actions[segment_id]
            is not candidate_case.prediction.actions[segment_id]
        )
        comparisons.append(
            EvalCaseComparison(
                baseline_case.sample_id,
                _quality_delta(baseline_case, candidate_case),
                changes,
            )
        )
    case_tuple = tuple(comparisons)
    return EvalComparisonReport(
        len(case_tuple),
        _mean_delta(tuple(comparison.delta for comparison in case_tuple)),
        case_tuple,
    )


def _degradation(delta: QualityDelta, metric: str) -> float:
    value = getattr(delta, f"{metric}_delta")
    if metric in {"retention_recall", "deletion_accuracy"}:
        return max(0.0, -value)
    return max(0.0, value)


def assess_release_quality(
    report: EvalComparisonReport,
    policy: ReleaseQualityPolicy,
) -> ReleaseQualityDecision:
    """Apply thresholds only when deciding whether a candidate may be released."""
    thresholds = (
        ("retention_recall", policy.max_retention_recall_drop),
        ("deletion_accuracy", policy.max_deletion_accuracy_drop),
        ("duration_error_ratio", policy.max_duration_error_increase),
        ("cut_word_rate", policy.max_cut_word_rate_increase),
        ("isolated_clip_rate", policy.max_isolated_clip_rate_increase),
        ("narrative_break_rate", policy.max_narrative_break_rate_increase),
    )
    violations: list[ReleaseQualityViolation] = []
    for metric, allowed in thresholds:
        worst = max(
            report.cases,
            key=lambda case: _degradation(case.delta, metric),
        )
        observed = _degradation(worst.delta, metric)
        if observed <= allowed:
            continue
        violations.append(
            ReleaseQualityViolation(
                metric,
                observed,
                allowed,
                worst.sample_id,
                worst.decision_changes,
            )
        )
    violation_tuple = tuple(violations)
    return ReleaseQualityDecision(not violation_tuple, violation_tuple)


__all__ = [
    "EvalCaseResult",
    "DecisionChange",
    "EvalCaseComparison",
    "EvalComparisonReport",
    "EvalReplay",
    "EvalRunResult",
    "QualityDelta",
    "ReleaseQualityDecision",
    "ReleaseQualityPolicy",
    "ReleaseQualityViolation",
    "assess_release_quality",
    "compare_eval_runs",
    "run_evaluation_directory",
]
