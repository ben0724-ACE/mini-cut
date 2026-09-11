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
from minicut.eval_sample import EvalSample

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


__all__ = [
    "EvalCaseResult",
    "EvalReplay",
    "EvalRunResult",
    "run_evaluation_directory",
]
