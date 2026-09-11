import unittest

from minicut.human_review import (
    HUMAN_REVIEW_RUBRIC_VERSION,
    BlindReviewRecord,
    CriterionReview,
    RegressionIssue,
    ReviewCriterion,
    create_blind_review_rubric,
    create_regression_issues,
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


class BlindReviewRecordTest(unittest.TestCase):
    def test_records_all_scores_and_round_trips_without_model_identity(self) -> None:
        record = BlindReviewRecord(
            sample_id="sample-01",
            reviewer_id="reviewer-a",
            reviews=(
                CriterionReview(
                    ReviewCriterion.CUT_NATURALNESS,
                    2,
                    ("clip-02",),
                    "句尾被截断。",
                ),
                CriterionReview(ReviewCriterion.NARRATIVE_CONTINUITY, 4),
                CriterionReview(ReviewCriterion.REDUNDANCY, 3),
                CriterionReview(ReviewCriterion.OVERALL_USABILITY, 4),
            ),
        )

        restored = BlindReviewRecord.from_dict(record.to_dict())

        self.assertEqual(restored, record)
        self.assertEqual(restored.rubric_version, HUMAN_REVIEW_RUBRIC_VERSION)
        self.assertNotIn("model", record.to_dict())
        self.assertNotIn("planner", record.to_dict())

    def test_rejects_incomplete_duplicate_or_unlocated_low_scores(self) -> None:
        complete = tuple(CriterionReview(criterion, 4) for criterion in ReviewCriterion)

        with self.assertRaisesRegex(ValueError, "every criterion"):
            BlindReviewRecord("sample-01", "reviewer-a", complete[:-1])
        with self.assertRaisesRegex(ValueError, "every criterion"):
            BlindReviewRecord(
                "sample-01",
                "reviewer-a",
                (*complete[:-1], complete[0]),
            )
        with self.assertRaisesRegex(ValueError, "low review score"):
            CriterionReview(ReviewCriterion.REDUNDANCY, 2)


class ReviewRegressionIssueTest(unittest.TestCase):
    def test_turns_each_low_score_into_a_locatable_regression_issue(self) -> None:
        record = BlindReviewRecord(
            sample_id="sample-01",
            reviewer_id="reviewer-a",
            reviews=(
                CriterionReview(
                    ReviewCriterion.CUT_NATURALNESS,
                    2,
                    ("clip-02",),
                    "句尾被截断。",
                ),
                CriterionReview(
                    ReviewCriterion.NARRATIVE_CONTINUITY,
                    1,
                    ("clip-03", "clip-04"),
                ),
                CriterionReview(ReviewCriterion.REDUNDANCY, 3),
                CriterionReview(ReviewCriterion.OVERALL_USABILITY, 4),
            ),
        )

        issues = create_regression_issues(record)

        self.assertEqual(
            issues,
            (
                RegressionIssue(
                    "sample-01",
                    ReviewCriterion.CUT_NATURALNESS,
                    ("clip-02",),
                    observed_score=2,
                    expected_min_score=3,
                    description="句尾被截断。",
                ),
                RegressionIssue(
                    "sample-01",
                    ReviewCriterion.NARRATIVE_CONTINUITY,
                    ("clip-03", "clip-04"),
                    observed_score=1,
                    expected_min_score=3,
                    description="低分项需要回归验证。",
                ),
            ),
        )
        self.assertEqual(RegressionIssue.from_dict(issues[0].to_dict()), issues[0])

    def test_passing_scores_do_not_create_regression_issues(self) -> None:
        record = BlindReviewRecord(
            "sample-01",
            "reviewer-a",
            tuple(CriterionReview(criterion, 3) for criterion in ReviewCriterion),
        )

        self.assertEqual(create_regression_issues(record), ())


if __name__ == "__main__":
    unittest.main()
