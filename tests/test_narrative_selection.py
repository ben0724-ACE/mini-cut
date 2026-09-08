import unittest

from minicut.edit_plan import ContentRequirement, EditBrief, EditIntensity
from minicut.local_analysis import LocalSegmentAnalysis, SegmentClassification
from minicut.narrative_outline import NarrativeOutline, NarrativeSection
from minicut.narrative_selection import (
    NarrativeRole,
    select_narrative_candidates,
)
from minicut.semantic_segment import SemanticSegment


def _segment(ordinal: int) -> SemanticSegment:
    return SemanticSegment(
        segment_id=f"segment-{ordinal}",
        text=f"内容 {ordinal}",
        start_ms=ordinal * 1_000,
        end_ms=ordinal * 1_000 + 800,
        utterance_ids=(f"utterance-{ordinal}",),
        word_ids=(f"word-{ordinal}",),
    )


def _analysis(
    ordinal: int,
    importance: float,
    dependencies: tuple[str, ...] = (),
) -> LocalSegmentAnalysis:
    return LocalSegmentAnalysis(
        segment_id=f"segment-{ordinal}",
        classification=SegmentClassification.CONTENT,
        importance=importance,
        dependency_ids=dependencies,
        rationale=f"理由 {ordinal}",
        has_classification_conflict=False,
    )


def _outline() -> NarrativeOutline:
    return NarrativeOutline(
        "主题",
        NarrativeSection("开场", ("segment-1",)),
        (NarrativeSection("观点", ("segment-2", "segment-3")),),
        NarrativeSection("结论", ("segment-4",)),
    )


class NarrativeSelectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.segments = tuple(_segment(index) for index in range(6))
        self.analyses = (
            _analysis(0, 0.4),
            _analysis(1, 0.8, ("segment-0",)),
            _analysis(2, 0.9),
            _analysis(3, 0.6),
            _analysis(4, 0.85),
            _analysis(5, 0.5),
        )

    def test_selects_narrative_evidence_and_dependency_closure(self) -> None:
        brief = EditBrief(
            4_000,
            EditIntensity.BALANCED,
            "自然",
            must_keep=(ContentRequirement("保留补充", ("segment-5",)),),
        )

        selection = select_narrative_candidates(
            brief, self.segments, self.analyses, _outline()
        )

        self.assertEqual(
            selection.candidate_ids,
            (
                "segment-0",
                "segment-1",
                "segment-2",
                "segment-3",
                "segment-4",
                "segment-5",
            ),
        )
        self.assertEqual(selection.required_ids, ("segment-5",))
        self.assertEqual(
            tuple(coverage.role for coverage in selection.coverages),
            (
                NarrativeRole.OPENING,
                NarrativeRole.CORE_POINT,
                NarrativeRole.CONCLUSION,
            ),
        )
        self.assertEqual(
            selection.coverages[1].segment_ids,
            ("segment-2", "segment-3"),
        )
        self.assertEqual(selection.dependencies_for("segment-1"), ("segment-0",))

    def test_filters_removed_or_dependency_broken_evidence(self) -> None:
        analyses = list(self.analyses)
        analyses[1] = _analysis(1, 0.8)
        analyses[2] = _analysis(2, 0.9, ("segment-0",))
        brief = EditBrief(
            4_000,
            EditIntensity.BALANCED,
            "自然",
            must_remove=(ContentRequirement("删除铺垫", ("segment-0",)),),
        )

        selection = select_narrative_candidates(
            brief, self.segments, tuple(analyses), _outline()
        )

        self.assertEqual(selection.coverages[1].segment_ids, ("segment-3",))
        self.assertNotIn("segment-0", selection.candidate_ids)
        self.assertNotIn("segment-2", selection.candidate_ids)

    def test_fails_when_a_narrative_role_has_no_viable_evidence(self) -> None:
        brief = EditBrief(
            4_000,
            EditIntensity.BALANCED,
            "自然",
            must_remove=(ContentRequirement("删除结论", ("segment-4",)),),
        )

        with self.assertRaisesRegex(ValueError, "conclusion"):
            select_narrative_candidates(brief, self.segments, self.analyses, _outline())

    def test_rejects_unknown_outline_and_conflicting_user_requirements(self) -> None:
        unknown_outline = NarrativeOutline(
            "主题",
            NarrativeSection("开场", ("unknown",)),
            _outline().core_points,
            _outline().conclusion,
        )
        conflicting_brief = EditBrief(
            4_000,
            EditIntensity.BALANCED,
            "自然",
            must_keep=(ContentRequirement("保留", ("segment-5",)),),
            must_remove=(ContentRequirement("删除", ("segment-5",)),),
        )

        with self.assertRaisesRegex(ValueError, "unknown"):
            select_narrative_candidates(
                EditBrief(4_000, EditIntensity.BALANCED, "自然"),
                self.segments,
                self.analyses,
                unknown_outline,
            )
        with self.assertRaisesRegex(ValueError, "conflict"):
            select_narrative_candidates(
                conflicting_brief,
                self.segments,
                self.analyses,
                _outline(),
            )


if __name__ == "__main__":
    unittest.main()
