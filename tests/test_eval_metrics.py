import unittest
from collections.abc import Callable

from minicut.eval_metrics import (
    EvalClip,
    EvalPrediction,
    evaluate_selection,
    evaluate_timeline_quality,
)
from minicut.eval_sample import (
    EvalLabel,
    EvalSample,
    EvalScenario,
    EvalSegment,
    EvalWord,
    ReferenceAction,
)


def _sample() -> EvalSample:
    return EvalSample(
        "sample-001",
        "media-001",
        EvalScenario.REPETITION_HEAVY,
        "zh",
        (
            EvalWord("w1", "重点", 0, 400),
            EvalWord("w2", "重复", 500, 700),
            EvalWord("w3", "结论", 800, 1_200),
            EvalWord("w4", "补充", 1_300, 1_600),
        ),
        (
            EvalSegment("s1", ("w1",), ReferenceAction.KEEP, (EvalLabel.CORE_CONTENT,)),
            EvalSegment("s2", ("w2",), ReferenceAction.DELETE, (EvalLabel.REPETITION,)),
            EvalSegment("s3", ("w3",), ReferenceAction.KEEP, (EvalLabel.CORE_CONTENT,)),
            EvalSegment(
                "s4",
                ("w4",),
                ReferenceAction.DELETE,
                (EvalLabel.OPTIONAL_CONTENT,),
            ),
        ),
    )


class EvalSelectionMetricsTest(unittest.TestCase):
    def test_computes_hand_verifiable_selection_and_duration_metrics(self) -> None:
        prediction = EvalPrediction(
            actions={
                "s1": ReferenceAction.KEEP,
                "s2": ReferenceAction.DELETE,
                "s3": ReferenceAction.DELETE,
                "s4": ReferenceAction.DELETE,
            },
            estimated_duration_ms=500,
        )

        metrics = evaluate_selection(_sample(), prediction)

        self.assertEqual(metrics.reference_kept_segments, 2)
        self.assertEqual(metrics.correctly_kept_segments, 1)
        self.assertEqual(metrics.retention_recall, 0.5)
        self.assertEqual(metrics.predicted_deleted_segments, 3)
        self.assertEqual(metrics.correctly_deleted_segments, 2)
        self.assertAlmostEqual(metrics.deletion_accuracy, 2 / 3)
        self.assertEqual(metrics.reference_duration_ms, 800)
        self.assertEqual(metrics.predicted_duration_ms, 500)
        self.assertEqual(metrics.duration_error_ms, 300)
        self.assertEqual(metrics.duration_error_ratio, 0.375)

    def test_rejects_missing_unknown_or_negative_prediction_data(self) -> None:
        invalid_calls: tuple[Callable[[], object], ...] = (
            lambda: evaluate_selection(
                _sample(), EvalPrediction({"s1": ReferenceAction.KEEP}, 400)
            ),
            lambda: evaluate_selection(
                _sample(),
                EvalPrediction(
                    {
                        "s1": ReferenceAction.KEEP,
                        "s2": ReferenceAction.DELETE,
                        "s3": ReferenceAction.KEEP,
                        "s4": ReferenceAction.DELETE,
                        "unknown": ReferenceAction.KEEP,
                    },
                    800,
                ),
            ),
            lambda: EvalPrediction(
                {
                    "s1": ReferenceAction.KEEP,
                    "s2": ReferenceAction.DELETE,
                    "s3": ReferenceAction.KEEP,
                    "s4": ReferenceAction.DELETE,
                },
                -1,
            ),
        )

        for invalid_call in invalid_calls:
            with self.subTest(invalid_call=invalid_call):
                with self.assertRaises(ValueError):
                    invalid_call()

    def test_uses_defined_scores_when_no_reference_keep_or_predicted_delete(
        self,
    ) -> None:
        all_deleted = EvalSample(
            "sample-empty-keep",
            "media-002",
            EvalScenario.PAUSE_HEAVY,
            "zh",
            (EvalWord("w1", "嗯", 0, 100),),
            (EvalSegment("s1", ("w1",), ReferenceAction.DELETE, (EvalLabel.FILLER,)),),
        )

        metrics = evaluate_selection(
            all_deleted,
            EvalPrediction({"s1": ReferenceAction.KEEP}, 0),
        )

        self.assertEqual(metrics.retention_recall, 1.0)
        self.assertEqual(metrics.deletion_accuracy, 1.0)
        self.assertEqual(metrics.duration_error_ratio, 0.0)


class EvalTimelineQualityMetricsTest(unittest.TestCase):
    def test_computes_cut_word_isolation_and_narrative_break_metrics(self) -> None:
        sample = EvalSample(
            "sample-quality",
            "media-quality",
            EvalScenario.FALSE_STARTS,
            "zh",
            (
                EvalWord("w1", "第一句", 0, 300),
                EvalWord("w2", "承接", 500, 800),
                EvalWord("w3", "结论", 1_000, 1_500),
            ),
            (
                EvalSegment(
                    "s1", ("w1",), ReferenceAction.KEEP, (EvalLabel.CORE_CONTENT,)
                ),
                EvalSegment(
                    "s2", ("w2",), ReferenceAction.KEEP, (EvalLabel.CORE_CONTENT,)
                ),
                EvalSegment(
                    "s3",
                    ("w3",),
                    ReferenceAction.KEEP,
                    (EvalLabel.NARRATIVE_DEPENDENCY,),
                    ("s2",),
                ),
            ),
        )
        prediction = EvalPrediction(
            {
                "s1": ReferenceAction.KEEP,
                "s2": ReferenceAction.DELETE,
                "s3": ReferenceAction.KEEP,
            },
            650,
            (
                EvalClip(50, 250, ("s1",)),
                EvalClip(1_000, 1_450, ("s3",)),
            ),
        )

        metrics = evaluate_timeline_quality(
            sample, prediction, isolated_clip_threshold_ms=300
        )

        self.assertEqual(metrics.clip_count, 2)
        self.assertEqual(metrics.cut_boundary_count, 4)
        self.assertEqual(metrics.cut_word_boundaries, 3)
        self.assertEqual(metrics.cut_word_rate, 0.75)
        self.assertEqual(metrics.isolated_clip_count, 1)
        self.assertEqual(metrics.isolated_clip_rate, 0.5)
        self.assertEqual(metrics.required_context_relationships, 1)
        self.assertEqual(metrics.narrative_break_count, 1)
        self.assertEqual(metrics.narrative_break_rate, 1.0)

    def test_rejects_nonpositive_threshold_or_clip_segment_mismatch(self) -> None:
        sample = _sample()
        valid_actions = {
            "s1": ReferenceAction.KEEP,
            "s2": ReferenceAction.DELETE,
            "s3": ReferenceAction.KEEP,
            "s4": ReferenceAction.DELETE,
        }

        with self.assertRaisesRegex(ValueError, "threshold"):
            evaluate_timeline_quality(
                sample,
                EvalPrediction(
                    valid_actions,
                    800,
                    (EvalClip(0, 400, ("s1",)), EvalClip(800, 1_200, ("s3",))),
                ),
                isolated_clip_threshold_ms=0,
            )

        with self.assertRaisesRegex(ValueError, "kept"):
            evaluate_timeline_quality(
                sample,
                EvalPrediction(
                    valid_actions,
                    400,
                    (EvalClip(0, 400, ("s1",)),),
                ),
            )


if __name__ == "__main__":
    unittest.main()
