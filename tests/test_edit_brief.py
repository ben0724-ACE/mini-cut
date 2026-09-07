import json
import unittest
from collections.abc import Callable

from minicut.edit_plan import ContentRequirement, EditBrief, EditIntensity


class ContentRequirementTest(unittest.TestCase):
    def test_requirement_can_hold_user_intent_and_resolved_segment_ids(self) -> None:
        requirement = ContentRequirement(
            instruction="保留完整的部署过程",
            segment_ids=("segment-2", "segment-3"),
        )

        self.assertEqual(
            ContentRequirement.from_dict(requirement.to_dict()),
            requirement,
        )

    def test_requirement_rejects_blank_text_and_invalid_segment_ids(self) -> None:
        invalid_factories: tuple[Callable[[], ContentRequirement], ...] = (
            lambda: ContentRequirement(" "),
            lambda: ContentRequirement("保留部署", ("",)),
            lambda: ContentRequirement("保留部署", ("segment-1", "segment-1")),
        )

        for index, create_requirement in enumerate(invalid_factories):
            with self.subTest(index=index):
                with self.assertRaises(ValueError):
                    create_requirement()


class EditBriefTest(unittest.TestCase):
    def test_brief_round_trips_all_user_editing_constraints(self) -> None:
        brief = EditBrief(
            target_duration_ms=180_000,
            intensity=EditIntensity.AGGRESSIVE,
            style="节奏紧凑，保留自然停顿",
            content_type="tutorial",
            language="zh",
            must_keep=(ContentRequirement("保留部署过程", ("segment-2",)),),
            must_remove=(ContentRequirement("删除片头寒暄"),),
        )

        restored = EditBrief.from_dict(
            json.loads(json.dumps(brief.to_dict(), ensure_ascii=False))
        )

        self.assertEqual(restored, brief)
        self.assertEqual(restored.target_duration_ms, 180_000)
        self.assertEqual(restored.intensity, EditIntensity.AGGRESSIVE)

    def test_brief_rejects_invalid_duration_or_blank_descriptors(self) -> None:
        invalid_factories: tuple[Callable[[], EditBrief], ...] = (
            lambda: EditBrief(0, EditIntensity.BALANCED, "concise"),
            lambda: EditBrief(-1, EditIntensity.BALANCED, "concise"),
            lambda: EditBrief(1_000, EditIntensity.BALANCED, " "),
            lambda: EditBrief(
                1_000,
                EditIntensity.BALANCED,
                "concise",
                content_type=" ",
            ),
            lambda: EditBrief(
                1_000,
                EditIntensity.BALANCED,
                "concise",
                language=" ",
            ),
        )

        for index, create_brief in enumerate(invalid_factories):
            with self.subTest(index=index):
                with self.assertRaises(ValueError):
                    create_brief()

    def test_default_metadata_supports_the_initial_spoken_video_workflow(self) -> None:
        brief = EditBrief(60_000, EditIntensity.CONSERVATIVE, "natural")

        self.assertEqual(brief.content_type, "spoken_video")
        self.assertEqual(brief.language, "auto")
        self.assertEqual(brief.must_keep, ())
        self.assertEqual(brief.must_remove, ())


if __name__ == "__main__":
    unittest.main()
