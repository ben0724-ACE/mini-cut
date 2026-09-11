"""Model-blind human review rubric for rendered edit quality."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

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


def _validate_opaque_id(value: str, field: str) -> None:
    if not value or any(
        character
        not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
        for character in value
    ):
        raise ValueError(f"{field} must be an opaque identifier, not a path")


@dataclass(frozen=True, slots=True)
class CriterionReview:
    criterion: ReviewCriterion
    score: int
    timeline_clip_ids: tuple[str, ...] = ()
    note: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.score, bool) or self.score not in range(1, 6):
            raise ValueError("review score must be between 1 and 5")
        if len(set(self.timeline_clip_ids)) != len(self.timeline_clip_ids):
            raise ValueError("review Timeline clip IDs must be unique")
        for clip_id in self.timeline_clip_ids:
            _validate_opaque_id(clip_id, "Timeline clip ID")
        if self.score <= 2 and not self.timeline_clip_ids:
            raise ValueError("low review score must identify a Timeline clip")

    def to_dict(self) -> dict[str, object]:
        return {
            "criterion": self.criterion.value,
            "score": self.score,
            "timeline_clip_ids": list(self.timeline_clip_ids),
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "CriterionReview":
        return cls(
            ReviewCriterion(cast(str, data["criterion"])),
            cast(int, data["score"]),
            tuple(cast(list[str], data.get("timeline_clip_ids", []))),
            cast(str, data.get("note", "")),
        )


@dataclass(frozen=True, slots=True)
class BlindReviewRecord:
    sample_id: str
    reviewer_id: str
    reviews: tuple[CriterionReview, ...]
    rubric_version: str = HUMAN_REVIEW_RUBRIC_VERSION

    def __post_init__(self) -> None:
        _validate_opaque_id(self.sample_id, "sample ID")
        _validate_opaque_id(self.reviewer_id, "reviewer ID")
        if self.rubric_version != HUMAN_REVIEW_RUBRIC_VERSION:
            raise ValueError("unsupported human review rubric version")
        actual = tuple(review.criterion for review in self.reviews)
        if actual != tuple(ReviewCriterion):
            raise ValueError("review record must contain every criterion in order")

    def to_dict(self) -> dict[str, object]:
        return {
            "rubric_version": self.rubric_version,
            "sample_id": self.sample_id,
            "reviewer_id": self.reviewer_id,
            "reviews": [review.to_dict() for review in self.reviews],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "BlindReviewRecord":
        return cls(
            sample_id=cast(str, data["sample_id"]),
            reviewer_id=cast(str, data["reviewer_id"]),
            reviews=tuple(
                CriterionReview.from_dict(item)
                for item in cast(list[dict[str, object]], data["reviews"])
            ),
            rubric_version=cast(str, data["rubric_version"]),
        )


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
    "BlindReviewRecord",
    "BlindReviewRubric",
    "CriterionReview",
    "ReviewCriterion",
    "ReviewDimension",
    "ScoreAnchor",
    "create_blind_review_rubric",
]
