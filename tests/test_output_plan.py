import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from minicut.errors import ProcessingError, UserInputError
from minicut.output_plan import (
    HighlightCandidate,
    OutputCollection,
    OutputItem,
    OutputPlan,
    OutputRole,
    validate_output_collection,
)
from minicut.output_repository import OutputCollectionRepository
from minicut.semantic_segment import SemanticSegment


def segments() -> tuple[SemanticSegment, ...]:
    return tuple(
        SemanticSegment(
            name, name, index * 1000, index * 1000 + 800, (f"u-{name}",), (f"w-{name}",)
        )
        for index, name in enumerate(("a", "b", "c"))
    )


def collection() -> OutputCollection:
    candidate = HighlightCandidate("candidate", "精彩观点", "原话理由", ("a", "b", "c"))
    plan = OutputPlan(
        "video-1",
        "candidate",
        "观点先行",
        (
            OutputItem("first", "c", OutputRole.BODY),
            OutputItem("second", "a", OutputRole.BODY),
            OutputItem("third", "b", OutputRole.BODY),
        ),
    )
    return OutputCollection("selected", "asset", (candidate,), (plan,))


class OutputPlanTest(unittest.TestCase):
    def test_collection_round_trip_and_repository_leave_existing_project_alone(
        self,
    ) -> None:
        value = collection()
        self.assertEqual(OutputCollection.from_dict(value.to_dict()), value)
        with TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = root / "manifest.json"
            legacy.write_text("existing project", encoding="utf-8")
            repo = OutputCollectionRepository(root, "selected")
            repo.write(value, segments())
            self.assertEqual(repo.read(segments()), value)
            self.assertEqual(legacy.read_text(encoding="utf-8"), "existing project")
            with patch.object(Path, "replace", side_effect=OSError("write failed")):
                with self.assertRaises(ProcessingError):
                    repo.write(value, segments())
            self.assertEqual(repo.read(segments()), value)
            self.assertEqual(list(repo.path.parent.glob("*.tmp")), [])
            repo.path.write_text("broken", encoding="utf-8")
            with self.assertRaises(UserInputError):
                repo.read(segments())

    def test_reference_validation(self) -> None:
        value = collection()
        plan = value.plans[0]
        for bad in (
            replace(value, plans=(replace(plan, candidate_id="unknown"),)),
            replace(
                value,
                plans=(
                    replace(
                        plan, items=(OutputItem("one", "missing", OutputRole.BODY),)
                    ),
                ),
            ),
            replace(
                value,
                candidates=(
                    replace(value.candidates[0], context_segment_ids=("missing",)),
                ),
            ),
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_output_collection(bad, segments())
        with self.assertRaises(ValueError):
            replace(plan, items=(plan.items[0], plan.items[0]))
        with self.assertRaises(ValueError):
            replace(plan, items=())
        with self.assertRaises(ValueError):
            replace(value, plans=(plan, plan))
        with self.assertRaises(ValueError):
            replace(value, schema_version=2)
        with self.assertRaises(ValueError):
            replace(value, asset_id="")
        with self.assertRaises(ValueError):
            OutputItem("x", "a", "invalid")  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            OutputCollectionRepository(Path("/project"), "../escape")


def test_transition_round_trip_legacy_default_and_invalid_values() -> None:
    plan = collection().plans[0]
    legacy = plan.to_dict()
    legacy.pop("hook_transition_ms")
    assert OutputPlan.from_dict(legacy).hook_transition_ms == 300
    for duration in (0, 150, 300, 500, 1000):
        updated = replace(plan, hook_transition_ms=duration)
        assert OutputPlan.from_dict(updated.to_dict()) == updated
    for invalid in (-1, 1001, True):
        with unittest.TestCase().assertRaises(ValueError):
            replace(plan, hook_transition_ms=invalid)
