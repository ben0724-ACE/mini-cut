import json
import unittest

from minicut.local_analysis import (
    SegmentAnalysisDetail,
    build_segment_detail_request,
    parse_segment_detail_response,
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


class SegmentAnalysisDetailTest(unittest.TestCase):
    def test_detail_round_trips_importance_dependencies_and_reason(self) -> None:
        detail = SegmentAnalysisDetail(
            segment_id="segment-1",
            importance=0.85,
            dependency_ids=("segment-0", "segment-2"),
            rationale="承接前文并引出结论。",
        )

        restored = SegmentAnalysisDetail.from_dict(
            json.loads(json.dumps(detail.to_dict(), ensure_ascii=False))
        )

        self.assertEqual(restored, detail)

    def test_detail_rejects_invalid_local_fields(self) -> None:
        invalid_factories = (
            lambda: SegmentAnalysisDetail("", 0.5, (), "理由"),
            lambda: SegmentAnalysisDetail("segment-1", -0.01, (), "理由"),
            lambda: SegmentAnalysisDetail("segment-1", 1.01, (), "理由"),
            lambda: SegmentAnalysisDetail("segment-1", 0.5, (), " "),
            lambda: SegmentAnalysisDetail("segment-1", 0.5, (), "理" * 201),
            lambda: SegmentAnalysisDetail(
                "segment-1", 0.5, ("segment-0", "segment-0"), "理由"
            ),
            lambda: SegmentAnalysisDetail("segment-1", 0.5, ("segment-1",), "理由"),
        )

        for factory in invalid_factories:
            with self.subTest(factory=factory):
                with self.assertRaises(ValueError):
                    factory()

    def test_prompt_includes_read_only_context_without_timestamps(self) -> None:
        target = _segment(1, "因此我们选择本地处理。")
        context = (_segment(0, "前面讨论了隐私。"), _segment(2, "接下来演示步骤。"))

        request = build_segment_detail_request(target, context, "model")
        payload = json.loads(request.user_prompt)

        self.assertEqual(payload["target"]["segment_id"], "segment-1")
        self.assertEqual(
            [item["segment_id"] for item in payload["read_only_context"]],
            ["segment-0", "segment-2"],
        )
        self.assertIn("must not modify", request.system_prompt)
        self.assertIn("dependency_ids", request.system_prompt)
        serialized = request.system_prompt + request.user_prompt
        self.assertNotIn("start_ms", serialized)
        self.assertNotIn("end_ms", serialized)

    def test_response_can_only_reference_target_and_supplied_context(self) -> None:
        target = _segment(1, "目标")
        context = (_segment(0, "前文"), _segment(2, "后文"))
        valid = json.dumps(
            {
                "segment_id": "segment-1",
                "importance": 0.7,
                "dependency_ids": ["segment-0"],
                "rationale": "依赖前文定义。",
            }
        )

        detail = parse_segment_detail_response(valid, target, context)

        self.assertEqual(detail.dependency_ids, ("segment-0",))

        invalid_payloads = (
            {**json.loads(valid), "segment_id": "segment-0"},
            {**json.loads(valid), "dependency_ids": ["segment-unknown"]},
            {**json.loads(valid), "context_decision": "delete"},
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(ValueError, "analysis detail"):
                    parse_segment_detail_response(
                        json.dumps(payload),
                        target,
                        context,
                    )

    def test_context_ids_must_be_unique_and_exclude_target(self) -> None:
        target = _segment(1, "目标")
        invalid_contexts = (
            (target,),
            (_segment(0, "前文"), _segment(0, "重复前文")),
        )

        for context in invalid_contexts:
            with self.subTest(context=context):
                with self.assertRaisesRegex(ValueError, "context"):
                    build_segment_detail_request(target, context, "model")


if __name__ == "__main__":
    unittest.main()
