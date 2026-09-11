"""Model-blind human review rubric for rendered edit quality."""

from dataclasses import dataclass
from enum import StrEnum

HUMAN_REVIEW_RUBRIC_VERSION = "human-review-v1"


class ReviewCriterion(StrEnum):
    CUT_NATURALNESS = "cut_naturalness"
    NARRATIVE_CONTINUITY = "narrative_continuity"
    REDUNDANCY = "redundancy"
    OVERALL_USABILITY = "overall_usability"


@dataclass(frozen=True, slots=True)
class ScoreAnchor:
    score: int
    description: str

    def __post_init__(self) -> None:
        if self.score not in range(1, 6):
            raise ValueError("review score must be between 1 and 5")
        if not self.description.strip():
            raise ValueError("review score description must not be blank")


@dataclass(frozen=True, slots=True)
class ReviewDimension:
    criterion: ReviewCriterion
    question: str
    anchors: tuple[ScoreAnchor, ...]

    def __post_init__(self) -> None:
        if not self.question.strip():
            raise ValueError("review question must not be blank")
        if tuple(anchor.score for anchor in self.anchors) != (1, 2, 3, 4, 5):
            raise ValueError("review dimension requires ordered anchors from 1 to 5")


@dataclass(frozen=True, slots=True)
class BlindReviewRubric:
    version: str
    criteria: tuple[ReviewDimension, ...]

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("review rubric version must not be blank")
        expected = tuple(ReviewCriterion)
        actual = tuple(dimension.criterion for dimension in self.criteria)
        if actual != expected:
            raise ValueError("review rubric must contain every criterion in order")


def _anchors(*descriptions: str) -> tuple[ScoreAnchor, ...]:
    return tuple(
        ScoreAnchor(score, description)
        for score, description in enumerate(descriptions, start=1)
    )


def create_blind_review_rubric() -> BlindReviewRubric:
    """Return the standard rubric without revealing how a cut was produced."""
    return BlindReviewRubric(
        HUMAN_REVIEW_RUBRIC_VERSION,
        (
            ReviewDimension(
                ReviewCriterion.CUT_NATURALNESS,
                "片段衔接听起来和看起来自然吗？",
                _anchors(
                    "频繁切断词语或动作，明显无法观看。",
                    "存在多处突兀衔接，持续影响理解。",
                    "有少量可察觉的突兀衔接，但基本可理解。",
                    "绝大多数衔接自然，仅有轻微瑕疵。",
                    "衔接流畅自然，没有可察觉的切断。",
                ),
            ),
            ReviewDimension(
                ReviewCriterion.NARRATIVE_CONTINUITY,
                "内容前后是否连贯并保留必要上下文？",
                _anchors(
                    "关键上下文大量缺失，内容无法理解。",
                    "多处因果或指代断裂，理解明显受阻。",
                    "主线可理解，但部分上下文衔接不足。",
                    "内容基本连贯，仅有轻微跳跃。",
                    "逻辑完整，因果、指代和上下文均清楚。",
                ),
            ),
            ReviewDimension(
                ReviewCriterion.REDUNDANCY,
                "成片是否去除了不必要的停顿、重复和赘述？",
                _anchors(
                    "大量无效内容残留，观看负担很重。",
                    "明显停顿、重复或赘述仍然较多。",
                    "仍有一些冗余，但整体节奏可以接受。",
                    "大部分冗余已去除，节奏较紧凑。",
                    "内容精炼，没有明显可继续删除的冗余。",
                ),
            ),
            ReviewDimension(
                ReviewCriterion.OVERALL_USABILITY,
                "这段成片距离可以直接使用还有多远？",
                _anchors(
                    "无法使用，需要重新剪辑。",
                    "需要大量修改后才能使用。",
                    "可作为粗剪，但仍需要若干修改。",
                    "只需少量调整即可使用。",
                    "无需修改即可直接使用。",
                ),
            ),
        ),
    )


__all__ = [
    "HUMAN_REVIEW_RUBRIC_VERSION",
    "BlindReviewRubric",
    "ReviewCriterion",
    "ReviewDimension",
    "ScoreAnchor",
    "create_blind_review_rubric",
]
