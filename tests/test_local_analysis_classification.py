import json
import unittest

from minicut.local_analysis import (
    SegmentClassification,
    SegmentClassificationResult,
    build_segment_classification_request,
    parse_segment_classification_response,
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


class SegmentClassificationTest(unittest.TestCase):
    def test_all_classifications_round_trip_through_json(self) -> None:
        for classification in SegmentClassification:
            with self.subTest(classification=classification):
                result = SegmentClassificationResult(
                    "segment-1",
                    classification,
                )
                restored = SegmentClassificationResult.from_dict(
                    json.loads(json.dumps(result.to_dict()))
                )
                self.assertEqual(restored, result)

        self.assertEqual(
            tuple(classification.value for classification in SegmentClassification),
            ("filler", "repeat", "false_start", "content"),
        )

    def test_result_rejects_blank_id_and_unknown_classification(self) -> None:
        with self.assertRaisesRegex(ValueError, "Segment ID"):
            SegmentClassificationResult(" ", SegmentClassification.CONTENT)

        with self.assertRaisesRegex(ValueError, "unknown"):
            SegmentClassificationResult.from_dict(
                {"segment_id": "segment-1", "classification": "unknown"}
            )

    def test_prompt_classifies_only_target_with_read_only_context(self) -> None:
        target = _segment(1, "嗯，我重新说。")
        context = (_segment(0, "上一句。"), _segment(2, "下一句。"))

        request = build_segment_classification_request(target, context, "model")
        payload = json.loads(request.user_prompt)

        self.assertEqual(payload["target"]["segment_id"], "segment-1")
        self.assertEqual(
            [item["segment_id"] for item in payload["read_only_context"]],
            ["segment-0", "segment-2"],
        )
        for classification in SegmentClassification:
            self.assertIn(classification.value, request.system_prompt)
        self.assertIn("must not classify", request.system_prompt)
        self.assertNotIn("start_ms", request.user_prompt)
        self.assertNotIn("end_ms", request.user_prompt)

    def test_parser_accepts_each_class_for_the_target(self) -> None:
        target = _segment(1, "目标")
        context = (_segment(0, "前文"), _segment(2, "后文"))

        for classification in SegmentClassification:
            with self.subTest(classification=classification):
                result = parse_segment_classification_response(
                    json.dumps(
                        {
                            "segment_id": "segment-1",
                            "classification": classification.value,
                        }
                    ),
                    target,
                    context,
                )
                self.assertEqual(result.classification, classification)

    def test_parser_rejects_context_changes_and_invalid_output(self) -> None:
        target = _segment(1, "目标")
        context = (_segment(0, "前文"), _segment(2, "后文"))
        invalid_payloads = (
            {"segment_id": "segment-0", "classification": "content"},
            {"segment_id": "segment-1", "classification": "unknown"},
            {
                "segment_id": "segment-1",
                "classification": "content",
                "context_classifications": {"segment-0": "filler"},
            },
        )

        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(ValueError, "classification"):
                    parse_segment_classification_response(
                        json.dumps(payload),
                        target,
                        context,
                    )


if __name__ == "__main__":
    unittest.main()
