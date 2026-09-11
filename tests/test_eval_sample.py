import json
import unittest

from minicut.eval_sample import (
    EVAL_SAMPLE_SCHEMA_VERSION,
    EvalLabel,
    EvalSample,
    EvalScenario,
    EvalSegment,
    EvalWord,
    ReferenceAction,
)


def _sample() -> EvalSample:
    return EvalSample(
        sample_id="sample-001",
        media_id="media-001",
        scenario=EvalScenario.FALSE_STARTS,
        language="zh",
        words=(
            EvalWord("word-1", "我", 0, 100),
            EvalWord("word-2", "重新说", 150, 500),
        ),
        segments=(
            EvalSegment(
                "segment-1",
                ("word-1",),
                ReferenceAction.DELETE,
                (EvalLabel.FALSE_START,),
            ),
            EvalSegment(
                "segment-2",
                ("word-2",),
                ReferenceAction.KEEP,
                (EvalLabel.CORE_CONTENT,),
                ("segment-1",),
            ),
        ),
    )


class EvalSampleTest(unittest.TestCase):
    def test_anonymous_reference_sample_round_trips_through_json(self) -> None:
        sample = _sample()

        payload = json.loads(json.dumps(sample.to_dict(), ensure_ascii=False))
        restored = EvalSample.from_dict(payload)

        self.assertEqual(restored, sample)
        self.assertEqual(payload["schema_version"], EVAL_SAMPLE_SCHEMA_VERSION)
        self.assertNotIn("source_path", payload)
        self.assertNotIn("person", payload)
        self.assertEqual(payload["media_id"], "media-001")

    def test_rejects_paths_duplicate_word_coverage_and_unknown_context(self) -> None:
        with self.assertRaisesRegex(ValueError, "opaque"):
            EvalSample(
                "sample-001",
                "/private/video.mov",
                EvalScenario.FLUENT,
                "zh",
                (EvalWord("word-1", "内容", 0, 100),),
                (
                    EvalSegment(
                        "segment-1",
                        ("word-1",),
                        ReferenceAction.KEEP,
                        (EvalLabel.CORE_CONTENT,),
                    ),
                ),
            )

        with self.assertRaisesRegex(ValueError, "exactly one"):
            EvalSample(
                "sample-001",
                "media-001",
                EvalScenario.REPETITION_HEAVY,
                "zh",
                (EvalWord("word-1", "重复", 0, 100),),
                (
                    EvalSegment(
                        "segment-1",
                        ("word-1",),
                        ReferenceAction.KEEP,
                        (EvalLabel.CORE_CONTENT,),
                    ),
                    EvalSegment(
                        "segment-2",
                        ("word-1",),
                        ReferenceAction.DELETE,
                        (EvalLabel.REPETITION,),
                    ),
                ),
            )

        with self.assertRaisesRegex(ValueError, "unknown"):
            EvalSample(
                "sample-001",
                "media-001",
                EvalScenario.FLUENT,
                "zh",
                (EvalWord("word-1", "内容", 0, 100),),
                (
                    EvalSegment(
                        "segment-1",
                        ("word-1",),
                        ReferenceAction.KEEP,
                        (EvalLabel.NARRATIVE_DEPENDENCY,),
                        ("missing",),
                    ),
                ),
            )


if __name__ == "__main__":
    unittest.main()
