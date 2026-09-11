import json
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from minicut.eval_metrics import EvalClip, EvalPrediction
from minicut.eval_runner import (
    ReleaseQualityPolicy,
    assess_release_quality,
    compare_eval_runs,
    run_evaluation_directory,
)
from minicut.eval_sample import (
    EvalLabel,
    EvalSample,
    EvalScenario,
    EvalSegment,
    EvalWord,
    ReferenceAction,
)


def _sample(sample_id: str) -> EvalSample:
    return EvalSample(
        sample_id,
        f"media-{sample_id}",
        EvalScenario.FLUENT,
        "zh",
        (
            EvalWord("w1", "重点", 0, 400),
            EvalWord("w2", "语气词", 500, 700),
        ),
        (
            EvalSegment("s1", ("w1",), ReferenceAction.KEEP, (EvalLabel.CORE_CONTENT,)),
            EvalSegment("s2", ("w2",), ReferenceAction.DELETE, (EvalLabel.FILLER,)),
        ),
    )


def _perfect_prediction(sample: EvalSample) -> EvalPrediction:
    del sample
    return EvalPrediction(
        {"s1": ReferenceAction.KEEP, "s2": ReferenceAction.DELETE},
        400,
        (EvalClip(0, 400, ("s1",)),),
    )


class EvalRunnerTest(unittest.TestCase):
    def test_replays_json_samples_in_stable_order_without_media_io(self) -> None:
        with TemporaryDirectory() as directory:
            samples = Path(directory)
            (samples / "b.json").write_text(
                json.dumps(_sample("sample-b").to_dict(), ensure_ascii=False),
                encoding="utf-8",
            )
            (samples / "a.json").write_text(
                json.dumps(_sample("sample-a").to_dict(), ensure_ascii=False),
                encoding="utf-8",
            )
            calls: list[str] = []

            def replay(sample: EvalSample) -> EvalPrediction:
                calls.append(sample.sample_id)
                return _perfect_prediction(sample)

            first = run_evaluation_directory(samples, replay)
            second = run_evaluation_directory(samples, replay)

            self.assertEqual(
                [case.sample_id for case in first.cases], ["sample-a", "sample-b"]
            )
            self.assertEqual(first, second)
            self.assertEqual(calls, ["sample-a", "sample-b"] * 2)
            self.assertTrue(
                all(case.selection.retention_recall == 1 for case in first.cases)
            )
            self.assertTrue(
                all(case.timeline.cut_word_boundaries == 0 for case in first.cases)
            )

    def test_rejects_duplicate_sample_ids(self) -> None:
        with TemporaryDirectory() as directory:
            samples = Path(directory)
            sample = _sample("duplicate")
            (samples / "one.json").write_text(
                json.dumps(sample.to_dict()), encoding="utf-8"
            )
            (samples / "two.json").write_text(
                json.dumps(replace(sample, media_id="media-second").to_dict()),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "duplicate"):
                run_evaluation_directory(samples, _perfect_prediction)


class EvalComparisonTest(unittest.TestCase):
    def test_compares_quality_and_locates_changed_segment_decisions(self) -> None:
        with TemporaryDirectory() as directory:
            samples = Path(directory)
            (samples / "sample.json").write_text(
                json.dumps(_sample("sample-a").to_dict()), encoding="utf-8"
            )
            baseline = run_evaluation_directory(samples, _perfect_prediction)

            def degraded(sample: EvalSample) -> EvalPrediction:
                del sample
                return EvalPrediction(
                    {"s1": ReferenceAction.DELETE, "s2": ReferenceAction.DELETE},
                    0,
                    (),
                )

            candidate = run_evaluation_directory(samples, degraded)

            report = compare_eval_runs(baseline, candidate)

            self.assertEqual(report.sample_count, 1)
            self.assertEqual(report.aggregate.retention_recall_delta, -1.0)
            self.assertEqual(report.aggregate.deletion_accuracy_delta, -0.5)
            self.assertEqual(report.aggregate.duration_error_ratio_delta, 1.0)
            self.assertEqual(report.cases[0].sample_id, "sample-a")
            self.assertEqual(len(report.cases[0].decision_changes), 1)
            change = report.cases[0].decision_changes[0]
            self.assertEqual(change.segment_id, "s1")
            self.assertIs(change.baseline_action, ReferenceAction.KEEP)
            self.assertIs(change.candidate_action, ReferenceAction.DELETE)

    def test_rejects_comparison_of_different_sample_sets(self) -> None:
        with (
            TemporaryDirectory() as first_directory,
            TemporaryDirectory() as second_directory,
        ):
            first = Path(first_directory)
            second = Path(second_directory)
            (first / "a.json").write_text(
                json.dumps(_sample("sample-a").to_dict()), encoding="utf-8"
            )
            (second / "b.json").write_text(
                json.dumps(_sample("sample-b").to_dict()), encoding="utf-8"
            )

            with self.assertRaisesRegex(ValueError, "same sample"):
                compare_eval_runs(
                    run_evaluation_directory(first, _perfect_prediction),
                    run_evaluation_directory(second, _perfect_prediction),
                )


class ReleaseQualityDecisionTest(unittest.TestCase):
    def test_blocks_release_and_locates_worst_sample_and_decision(self) -> None:
        with TemporaryDirectory() as directory:
            samples = Path(directory)
            (samples / "sample.json").write_text(
                json.dumps(_sample("sample-a").to_dict()), encoding="utf-8"
            )
            baseline = run_evaluation_directory(samples, _perfect_prediction)

            def degraded(sample: EvalSample) -> EvalPrediction:
                del sample
                return EvalPrediction(
                    {"s1": ReferenceAction.DELETE, "s2": ReferenceAction.DELETE},
                    0,
                    (),
                )

            report = compare_eval_runs(
                baseline, run_evaluation_directory(samples, degraded)
            )
            policy = ReleaseQualityPolicy(
                max_retention_recall_drop=0.1,
                max_deletion_accuracy_drop=1.0,
                max_duration_error_increase=2.0,
                max_cut_word_rate_increase=1.0,
                max_isolated_clip_rate_increase=1.0,
                max_narrative_break_rate_increase=1.0,
            )

            decision = assess_release_quality(report, policy)

            self.assertFalse(decision.can_release)
            self.assertEqual(len(decision.violations), 1)
            violation = decision.violations[0]
            self.assertEqual(violation.metric, "retention_recall")
            self.assertEqual(violation.observed_degradation, 1.0)
            self.assertEqual(violation.allowed_degradation, 0.1)
            self.assertEqual(violation.worst_sample_id, "sample-a")
            self.assertEqual(violation.decision_changes[0].segment_id, "s1")

    def test_allows_release_at_threshold_and_rejects_negative_policy(self) -> None:
        with TemporaryDirectory() as directory:
            samples = Path(directory)
            (samples / "sample.json").write_text(
                json.dumps(_sample("sample-a").to_dict()), encoding="utf-8"
            )
            run = run_evaluation_directory(samples, _perfect_prediction)
            report = compare_eval_runs(run, run)
            policy = ReleaseQualityPolicy(
                max_retention_recall_drop=0,
                max_deletion_accuracy_drop=0,
                max_duration_error_increase=0,
                max_cut_word_rate_increase=0,
                max_isolated_clip_rate_increase=0,
                max_narrative_break_rate_increase=0,
            )

            self.assertTrue(assess_release_quality(report, policy).can_release)

        with self.assertRaisesRegex(ValueError, "negative"):
            ReleaseQualityPolicy(
                max_retention_recall_drop=-0.1,
                max_deletion_accuracy_drop=0,
                max_duration_error_increase=0,
                max_cut_word_rate_increase=0,
                max_isolated_clip_rate_increase=0,
                max_narrative_break_rate_increase=0,
            )


if __name__ == "__main__":
    unittest.main()
