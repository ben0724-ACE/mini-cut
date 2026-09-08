"""Deterministic offline edit planning from semantic segment labels."""

from minicut.edit_plan import (
    ContentRequirement,
    EditAction,
    EditBrief,
    EditDecision,
    EditIntensity,
    EditPlan,
    PlannerKind,
    PlanProvenance,
    ReasonCode,
    validate_edit_plan,
)
from minicut.semantic_segment import SegmentLabel, SemanticSegment

RULE_POLICY_VERSION = "rule-policy-v1"

_DELETION_LABELS = {
    EditIntensity.CONSERVATIVE: frozenset({SegmentLabel.SILENCE}),
    EditIntensity.BALANCED: frozenset({SegmentLabel.SILENCE, SegmentLabel.FILLER}),
    EditIntensity.AGGRESSIVE: frozenset(
        {
            SegmentLabel.SILENCE,
            SegmentLabel.FILLER,
            SegmentLabel.FALSE_START,
            SegmentLabel.REPETITION_CANDIDATE,
        }
    ),
}


def _requirement_ids(
    requirements: tuple[ContentRequirement, ...],
) -> set[str]:
    return {
        segment_id
        for requirement in requirements
        for segment_id in requirement.segment_ids
    }


class RulePlanner:
    """Create a complete, reproducible plan without calling a model."""

    def plan(
        self,
        brief: EditBrief,
        segments: tuple[SemanticSegment, ...],
    ) -> EditPlan:
        """Apply the selected label policy without violating protected context."""
        must_keep_ids = _requirement_ids(brief.must_keep)
        must_remove_ids = _requirement_ids(brief.must_remove)
        deletion_labels = _DELETION_LABELS[brief.intensity]
        deleted_ids = {
            segment.segment_id
            for segment in segments
            if any(label in deletion_labels for label in segment.labels)
        } | must_remove_ids
        deleted_ids -= must_keep_ids

        changed = True
        while changed:
            changed = False
            for segment in segments:
                if segment.segment_id in deleted_ids:
                    continue
                for dependency in segment.context_dependencies:
                    if dependency.segment_id not in deleted_ids:
                        continue
                    if dependency.segment_id in must_remove_ids:
                        raise ValueError(
                            "must_remove requirement conflicts with kept context"
                        )
                    deleted_ids.remove(dependency.segment_id)
                    changed = True

        decisions = tuple(
            self._decision(segment, deleted_ids, must_keep_ids, must_remove_ids)
            for segment in segments
        )
        delete_count = sum(
            decision.action is EditAction.DELETE for decision in decisions
        )
        plan = EditPlan(
            brief=brief,
            decisions=decisions,
            summary=(
                f"Rule planner kept {len(decisions) - delete_count} segments "
                f"and deleted {delete_count} segments."
            ),
            provenance=PlanProvenance(
                planner=PlannerKind.RULE,
                model="none",
                prompt_version="none",
                policy_version=RULE_POLICY_VERSION,
            ),
        )
        validate_edit_plan(plan, segments)
        return plan

    @staticmethod
    def _decision(
        segment: SemanticSegment,
        deleted_ids: set[str],
        must_keep_ids: set[str],
        must_remove_ids: set[str],
    ) -> EditDecision:
        if segment.segment_id in must_keep_ids:
            action = EditAction.KEEP
            reason = ReasonCode.USER_REQUIRED
            explanation = "Kept because the user explicitly required this segment."
        elif segment.segment_id in must_remove_ids:
            action = EditAction.DELETE
            reason = ReasonCode.USER_REQUIRED
            explanation = "Deleted because the user explicitly required its removal."
        elif segment.segment_id in deleted_ids:
            action = EditAction.DELETE
            if SegmentLabel.SILENCE in segment.labels:
                reason = ReasonCode.SILENCE
                explanation = "Deleted because the segment is explicit silence."
            elif SegmentLabel.FILLER in segment.labels:
                reason = ReasonCode.FILLER
                explanation = "Deleted because the segment is pure filler."
            elif SegmentLabel.FALSE_START in segment.labels:
                reason = ReasonCode.FALSE_START
                explanation = "Deleted because the segment is a false start."
            else:
                reason = ReasonCode.REPETITION
                explanation = "Deleted because the segment repeats adjacent content."
        else:
            action = EditAction.KEEP
            reason = ReasonCode.CONTENT
            explanation = "Kept because no deterministic deletion rule applies."

        return EditDecision(
            segment_id=segment.segment_id,
            action=action,
            reason=reason,
            confidence=1.0,
            explanation=explanation,
            labels=tuple(label.value for label in segment.labels),
        )


__all__ = ["RULE_POLICY_VERSION", "RulePlanner"]
