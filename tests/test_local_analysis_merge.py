import unittest

from minicut.edit_plan import (
    ContentRequirement,
    EditAction,
    EditBrief,
    EditIntensity,
    ReasonCode,
)
from minicut.local_analysis import (
    LocalAnalysisJudgment,
    LocalSegmentAnalysis,
    SegmentAnalysisDetail,
    SegmentClassification,
    SegmentClassificationResult,
    build_local_decisions,
    merge_local_judgments,
)
from minicut.semantic_segment import SegmentLabel, SemanticSegment


def _segment(ordinal: int) -> SemanticSegment:
    return SemanticSegment(
        segment_id=f"segment-{ordinal}",
        text=f"内容 {ordinal}",
        start_ms=ordinal * 1_000,
        end_ms=ordinal * 1_000 + 800,
        utterance_ids=(f"utterance-{ordinal}",),
        word_ids=(f"word-{ordinal}",),
        labels=(SegmentLabel.CONTENT,),
    )


def _judgment(
    segment_id: str,
    classification: SegmentClassification,
    importance: float,
    dependencies: tuple[str, ...] = (),
    rationale: str = "局部判断。",
) -> LocalAnalysisJudgment:
    return LocalAnalysisJudgment(
        SegmentClassificationResult(segment_id, classification),
        SegmentAnalysisDetail(
            segment_id,
            importance,
            dependencies,
            rationale,
        ),
    )


class LocalAnalysisMergeTest(unittest.TestCase):
    def test_overlapping_consistent_judgments_merge_deterministically(self) -> None:
        segments = (_segment(0), _segment(1), _segment(2))
        judgments = (
            _judgment(
                "segment-1",
                SegmentClassification.CONTENT,
                0.6,
                ("segment-2",),
                "依赖后文。",
            ),
            _judgment("segment-0", SegmentClassification.CONTENT, 0.7),
            _judgment(
                "segment-1",
                SegmentClassification.CONTENT,
                0.9,
                ("segment-0",),
                "依赖前文定义。",
            ),
            _judgment("segment-2", SegmentClassification.CONTENT, 0.8),
        )

        first = merge_local_judgments(segments, judgments)
        second = merge_local_judgments(segments, judgments)

        self.assertEqual(first, second)
        self.assertEqual(
            tuple(analysis.segment_id for analysis in first),
            ("segment-0", "segment-1", "segment-2"),
        )
        self.assertEqual(first[1].importance, 0.9)
        self.assertEqual(first[1].dependency_ids, ("segment-0", "segment-2"))
        self.assertEqual(first[1].rationale, "依赖前文定义。")
        self.assertFalse(first[1].has_classification_conflict)

    def test_conflicting_classifications_fall_back_to_content(self) -> None:
        segments = (_segment(0),)
        judgments = (
            _judgment("segment-0", SegmentClassification.FILLER, 0.4),
            _judgment("segment-0", SegmentClassification.CONTENT, 0.8),
        )

        analyses = merge_local_judgments(segments, judgments)
        decisions = build_local_decisions(
            EditBrief(1_000, EditIntensity.BALANCED, "natural"),
            segments,
            analyses,
        )

        self.assertEqual(analyses[0].classification, SegmentClassification.CONTENT)
        self.assertTrue(analyses[0].has_classification_conflict)
        self.assertEqual(decisions[0].action, EditAction.KEEP)
        self.assertEqual(decisions[0].reason, ReasonCode.CONTENT)
        self.assertIn("classification_conflict", decisions[0].labels)

    def test_each_removable_class_uses_a_standard_reason_code(self) -> None:
        segments = tuple(_segment(index) for index in range(4))
        classifications = (
            SegmentClassification.FILLER,
            SegmentClassification.REPEAT,
            SegmentClassification.FALSE_START,
            SegmentClassification.CONTENT,
        )
        analyses = merge_local_judgments(
            segments,
            tuple(
                _judgment(segment.segment_id, classification, 0.5)
                for segment, classification in zip(
                    segments,
                    classifications,
                    strict=True,
                )
            ),
        )

        decisions = build_local_decisions(
            EditBrief(2_000, EditIntensity.BALANCED, "natural"),
            segments,
            analyses,
        )

        self.assertEqual(
            tuple((decision.action, decision.reason) for decision in decisions),
            (
                (EditAction.DELETE, ReasonCode.FILLER),
                (EditAction.DELETE, ReasonCode.REPETITION),
                (EditAction.DELETE, ReasonCode.FALSE_START),
                (EditAction.KEEP, ReasonCode.CONTENT),
            ),
        )

    def test_must_keep_and_kept_dependencies_override_model_deletion(self) -> None:
        segments = (_segment(0), _segment(1), _segment(2))
        analyses = merge_local_judgments(
            segments,
            (
                _judgment("segment-0", SegmentClassification.FILLER, 0.2),
                _judgment(
                    "segment-1",
                    SegmentClassification.CONTENT,
                    0.9,
                    ("segment-0",),
                ),
                _judgment("segment-2", SegmentClassification.REPEAT, 0.3),
            ),
        )
        brief = EditBrief(
            2_000,
            EditIntensity.BALANCED,
            "natural",
            must_keep=(ContentRequirement("保留强调", ("segment-2",)),),
        )

        decisions = build_local_decisions(brief, segments, analyses)

        self.assertEqual(
            tuple(decision.action for decision in decisions),
            (EditAction.KEEP, EditAction.KEEP, EditAction.KEEP),
        )
        self.assertEqual(decisions[2].reason, ReasonCode.USER_REQUIRED)
        self.assertIn("context_required", decisions[0].labels)

    def test_judgment_components_must_reference_the_same_segment(self) -> None:
        with self.assertRaisesRegex(ValueError, "same Segment"):
            LocalAnalysisJudgment(
                SegmentClassificationResult(
                    "segment-0",
                    SegmentClassification.CONTENT,
                ),
                SegmentAnalysisDetail("segment-1", 0.5, (), "理由"),
            )

    def test_merge_rejects_unknown_missing_and_unknown_dependency_ids(self) -> None:
        segments = (_segment(0), _segment(1))
        invalid_cases = (
            (
                "unknown",
                (
                    _judgment("segment-0", SegmentClassification.CONTENT, 0.5),
                    _judgment("unknown", SegmentClassification.CONTENT, 0.5),
                ),
            ),
            (
                "missing",
                (_judgment("segment-0", SegmentClassification.CONTENT, 0.5),),
            ),
            (
                "dependency",
                (
                    _judgment(
                        "segment-0",
                        SegmentClassification.CONTENT,
                        0.5,
                        ("unknown",),
                    ),
                    _judgment("segment-1", SegmentClassification.CONTENT, 0.5),
                ),
            ),
        )

        for message, judgments in invalid_cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    merge_local_judgments(segments, judgments)

    def test_merged_analysis_round_trips_through_json(self) -> None:
        analysis = LocalSegmentAnalysis(
            "segment-1",
            SegmentClassification.CONTENT,
            0.9,
            ("segment-0",),
            "核心论点。",
            False,
        )

        restored = LocalSegmentAnalysis.from_dict(analysis.to_dict())

        self.assertEqual(restored, analysis)


if __name__ == "__main__":
    unittest.main()
