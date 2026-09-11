import json
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from minicut.eval_metrics import EvalClip, EvalPrediction
from minicut.eval_runner import run_evaluation_directory
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


if __name__ == "__main__":
    unittest.main()
