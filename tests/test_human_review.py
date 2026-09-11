import unittest

from minicut.human_review import (
    HUMAN_REVIEW_RUBRIC_VERSION,
    ReviewCriterion,
    create_blind_review_rubric,
)


class BlindReviewRubricTest(unittest.TestCase):
    def test_defines_complete_five_point_anchors_for_each_review_dimension(
        self,
    ) -> None:
        rubric = create_blind_review_rubric()

        self.assertEqual(rubric.version, HUMAN_REVIEW_RUBRIC_VERSION)
        self.assertEqual(
            tuple(item.criterion for item in rubric.criteria),
            (
                ReviewCriterion.CUT_NATURALNESS,
                ReviewCriterion.NARRATIVE_CONTINUITY,
                ReviewCriterion.REDUNDANCY,
                ReviewCriterion.OVERALL_USABILITY,
            ),
        )
        for item in rubric.criteria:
            with self.subTest(criterion=item.criterion):
                self.assertEqual(
                    tuple(anchor.score for anchor in item.anchors), (1, 2, 3, 4, 5)
                )
                self.assertTrue(
                    all(anchor.description.strip() for anchor in item.anchors)
                )
                self.assertTrue(item.question.strip())

    def test_rubric_is_blind_to_model_policy_and_version_identity(self) -> None:
        rubric = create_blind_review_rubric()
        visible_text = " ".join(
            text
            for item in rubric.criteria
            for text in (
                item.question,
                *(anchor.description for anchor in item.anchors),
            )
        )

        for hidden_term in ("model", "provider", "planner", "policy", "版本", "模型"):
            with self.subTest(hidden_term=hidden_term):
                self.assertNotIn(hidden_term, visible_text.lower())


if __name__ == "__main__":
    unittest.main()
