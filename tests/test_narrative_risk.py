import unittest

from minicut.narrative_risk import (
    NarrativeBreakKind,
    detect_narrative_break_risks,
)
from minicut.narrative_selection import (
    DurationFallback,
    NarrativeCandidate,
    NarrativeCandidateSelection,
    NarrativeCoverage,
    NarrativeRole,
    TargetDurationSelection,
)
from minicut.semantic_segment import SemanticSegment


def _segment(ordinal: int, text: str) -> SemanticSegment:
    return SemanticSegment(
        segment_id=f"segment-{ordinal}",
        text=text,
        start_ms=ordinal * 1_000,
        end_ms=ordinal * 1_000 + 800,
        utterance_ids=(f"utterance-{ordinal}",),
        word_ids=(f"word-{ordinal}",),
    )


def _selection(
    dependency_ids: tuple[str, ...] = (),
) -> NarrativeCandidateSelection:
    candidates = (
        NarrativeCandidate("segment-0", 0.7, ()),
        NarrativeCandidate("segment-1", 0.8, ()),
        NarrativeCandidate("segment-2", 0.9, dependency_ids),
        NarrativeCandidate("segment-3", 0.8, ()),
    )
    return NarrativeCandidateSelection(
        candidates,
        (),
        (
            NarrativeCoverage(NarrativeRole.OPENING, 0, ("segment-0",)),
            NarrativeCoverage(NarrativeRole.CORE_POINT, 0, ("segment-2",)),
            NarrativeCoverage(NarrativeRole.CONCLUSION, 0, ("segment-3",)),
        ),
    )


def _duration_selection(
    selected_ids: tuple[str, ...],
) -> TargetDurationSelection:
    return TargetDurationSelection(
        selected_ids,
        len(selected_ids) * 800,
        len(selected_ids) * 800,
        True,
        DurationFallback.NONE,
        "达到目标。",
    )


class NarrativeBreakRiskTest(unittest.TestCase):
    def test_detects_pronoun_causal_and_reference_after_a_cut(self) -> None:
        cases = (
            ("它解决了这个问题。", NarrativeBreakKind.PRONOUN),
            ("因此我们选择本地运行。", NarrativeBreakKind.CAUSAL),
            ("如前所述，这一步最重要。", NarrativeBreakKind.REFERENCE),
        )

        for text, expected_kind in cases:
            with self.subTest(text=text):
                segments = (
                    _segment(0, "开场。"),
                    _segment(1, "被删除的上下文。"),
                    _segment(2, text),
                    _segment(3, "结论。"),
                )
                risks = detect_narrative_break_risks(
                    segments,
                    _selection(),
                    _duration_selection(("segment-0", "segment-2", "segment-3")),
                )

                self.assertEqual(len(risks), 1)
                self.assertEqual(risks[0].segment_id, "segment-2")
                self.assertEqual(risks[0].kind, expected_kind)
                self.assertEqual(risks[0].missing_context_ids, ("segment-1",))

    def test_does_not_flag_marker_when_preceding_source_is_kept(self) -> None:
        segments = (
            _segment(0, "开场。"),
            _segment(1, "解释原因。"),
            _segment(2, "因此得出结论。"),
            _segment(3, "结论。"),
        )

        risks = detect_narrative_break_risks(
            segments,
            _selection(),
            _duration_selection(("segment-0", "segment-1", "segment-2", "segment-3")),
        )

        self.assertEqual(risks, ())

    def test_reports_missing_declared_dependency_as_reference_break(self) -> None:
        segments = (
            _segment(0, "开场。"),
            _segment(1, "定义关键概念。"),
            _segment(2, "这里继续展开。"),
            _segment(3, "结论。"),
        )

        risks = detect_narrative_break_risks(
            segments,
            _selection(("segment-1",)),
            _duration_selection(("segment-0", "segment-2", "segment-3")),
        )

        self.assertEqual(len(risks), 1)
        self.assertEqual(risks[0].kind, NarrativeBreakKind.REFERENCE)
        self.assertEqual(risks[0].missing_context_ids, ("segment-1",))
        self.assertIn("declared dependency", risks[0].explanation)

    def test_rejects_unknown_selected_segment(self) -> None:
        segments = (
            _segment(0, "开场。"),
            _segment(1, "内容。"),
            _segment(2, "观点。"),
            _segment(3, "结论。"),
        )

        with self.assertRaisesRegex(ValueError, "unknown"):
            detect_narrative_break_risks(
                segments,
                _selection(),
                _duration_selection(("segment-0", "unknown")),
            )


if __name__ == "__main__":
    unittest.main()
