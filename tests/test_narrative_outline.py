import json
import unittest
from collections.abc import Callable

from minicut.edit_plan import EditBrief, EditIntensity
from minicut.local_analysis import LocalSegmentAnalysis, SegmentClassification
from minicut.narrative_outline import (
    NarrativeOutline,
    NarrativeSection,
    build_narrative_outline_request,
    parse_narrative_outline_response,
)
from minicut.semantic_segment import SegmentLabel, SemanticSegment


def _segment(ordinal: int, text: str) -> SemanticSegment:
    return SemanticSegment(
        segment_id=f"segment-{ordinal}",
        text=text,
        start_ms=ordinal * 1_000,
        end_ms=ordinal * 1_000 + 800,
        utterance_ids=(f"utterance-{ordinal}",),
        word_ids=(f"word-{ordinal}",),
        labels=(SegmentLabel.CONTENT,),
    )


def _analysis(ordinal: int, importance: float) -> LocalSegmentAnalysis:
    return LocalSegmentAnalysis(
        segment_id=f"segment-{ordinal}",
        classification=SegmentClassification.CONTENT,
        importance=importance,
        dependency_ids=(),
        rationale=f"片段 {ordinal} 的局部理由。",
        has_classification_conflict=False,
    )


class NarrativeOutlineModelTest(unittest.TestCase):
    def test_outline_round_trips_all_narrative_roles(self) -> None:
        outline = NarrativeOutline(
            topic="本地 AI 剪辑",
            opening=NarrativeSection("用创作者痛点开场。", ("segment-0",)),
            core_points=(
                NarrativeSection("解释本地转写。", ("segment-1",)),
                NarrativeSection("说明自动规划。", ("segment-2",)),
            ),
            conclusion=NarrativeSection("总结隐私与效率。", ("segment-3",)),
        )

        restored = NarrativeOutline.from_dict(
            json.loads(json.dumps(outline.to_dict(), ensure_ascii=False))
        )

        self.assertEqual(restored, outline)

    def test_outline_rejects_blank_or_incomplete_roles(self) -> None:
        valid_section = NarrativeSection("摘要", ("segment-0",))
        invalid_factories: tuple[Callable[[], object], ...] = (
            lambda: NarrativeSection(" ", ("segment-0",)),
            lambda: NarrativeSection("摘要", ()),
            lambda: NarrativeSection("摘要", ("",)),
            lambda: NarrativeSection("摘要", ("segment-0", "segment-0")),
            lambda: NarrativeOutline(
                " ", valid_section, (valid_section,), valid_section
            ),
            lambda: NarrativeOutline("主题", valid_section, (), valid_section),
        )

        for create_value in invalid_factories:
            with self.subTest(create_value=create_value):
                with self.assertRaises(ValueError):
                    create_value()


class NarrativeOutlinePromptTest(unittest.TestCase):
    def setUp(self) -> None:
        self.segments = (
            _segment(0, "开场提出问题。"),
            _segment(1, "核心解释方案。"),
            _segment(2, "结尾总结价值。"),
        )
        self.analyses = tuple(
            _analysis(index, importance)
            for index, importance in enumerate((0.7, 0.95, 0.8))
        )
        self.brief = EditBrief(60_000, EditIntensity.BALANCED, "自然紧凑")

    def test_prompt_contains_brief_and_merged_analysis_without_timestamps(self) -> None:
        request = build_narrative_outline_request(
            self.brief,
            self.segments,
            self.analyses,
            "deepseek-v4-flash",
        )
        payload = json.loads(request.user_prompt)

        self.assertEqual(payload["brief"], self.brief.to_dict())
        self.assertEqual(
            payload["allowed_segment_ids"],
            ["segment-0", "segment-1", "segment-2"],
        )
        self.assertEqual(payload["segments"][1]["importance"], 0.95)
        self.assertEqual(payload["segments"][1]["text"], "核心解释方案。")
        self.assertIn("opening", request.system_prompt)
        self.assertIn("core_points", request.system_prompt)
        self.assertIn("conclusion", request.system_prompt)
        serialized = request.system_prompt + request.user_prompt
        self.assertNotIn("start_ms", serialized)
        self.assertNotIn("end_ms", serialized)
        self.assertNotIn("word_ids", serialized)

    def test_request_requires_exactly_one_analysis_per_segment(self) -> None:
        invalid_analyses = (
            self.analyses[:-1],
            self.analyses + (self.analyses[0],),
            self.analyses[:-1] + (_analysis(9, 0.5),),
        )

        for analyses in invalid_analyses:
            with self.subTest(analyses=analyses):
                with self.assertRaisesRegex(ValueError, "analyses"):
                    build_narrative_outline_request(
                        self.brief,
                        self.segments,
                        analyses,
                        "model",
                    )

    def test_response_parses_only_known_segment_references(self) -> None:
        payload = {
            "topic": "本地 AI 剪辑",
            "opening": {
                "summary": "提出问题。",
                "segment_ids": ["segment-0"],
            },
            "core_points": [
                {
                    "summary": "解释方案。",
                    "segment_ids": ["segment-1"],
                }
            ],
            "conclusion": {
                "summary": "总结价值。",
                "segment_ids": ["segment-2"],
            },
        }

        outline = parse_narrative_outline_response(
            json.dumps(payload, ensure_ascii=False), self.segments
        )

        self.assertEqual(outline.topic, "本地 AI 剪辑")
        self.assertEqual(outline.opening.segment_ids, ("segment-0",))
        self.assertEqual(outline.core_points[0].segment_ids, ("segment-1",))
        self.assertEqual(outline.conclusion.segment_ids, ("segment-2",))

        invalid_payloads = (
            {**payload, "unexpected": True},
            {**payload, "opening": {"summary": "缺少引用"}},
            {
                **payload,
                "conclusion": {
                    "summary": "未知引用",
                    "segment_ids": ["segment-unknown"],
                },
            },
            {**payload, "core_points": []},
        )
        for invalid_payload in invalid_payloads:
            with self.subTest(payload=invalid_payload):
                with self.assertRaisesRegex(ValueError, "narrative outline"):
                    parse_narrative_outline_response(
                        json.dumps(invalid_payload, ensure_ascii=False),
                        self.segments,
                    )


if __name__ == "__main__":
    unittest.main()
