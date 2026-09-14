"""One initial proposal and at most one measured semantic revision."""

from dataclasses import dataclass, replace

from minicut.highlight_brief import HighlightBrief
from minicut.highlight_planner import HighlightPlanner, HighlightProposal
from minicut.highlight_selection import HighlightSelection, select_highlights
from minicut.semantic_segment import (
    ContextDirection,
    SegmentContextDependency,
    SemanticSegment,
)


def attach_continuation_context(
    segments: tuple[SemanticSegment, ...],
) -> tuple[SemanticSegment, ...]:
    result: list[SemanticSegment] = []
    for index, segment in enumerate(segments):
        if index + 1 < len(segments) and segment.text.rstrip().endswith(
            (",", "，", "、", ":", "：")
        ):
            following = segments[index + 1].segment_id
            if following not in {d.segment_id for d in segment.context_dependencies}:
                segment = replace(
                    segment,
                    context_dependencies=(
                        *segment.context_dependencies,
                        SegmentContextDependency(following, ContextDirection.FOLLOWING),
                    ),
                )
        result.append(segment)
    return tuple(result)


@dataclass(frozen=True, slots=True)
class HighlightWorkflowResult:
    proposal: HighlightProposal
    selection: HighlightSelection
    revised: bool


def revision_feedback(
    proposal: HighlightProposal,
    brief: HighlightBrief,
    segments: tuple[SemanticSegment, ...],
    notes: tuple[str, ...],
) -> dict[str, object]:
    compact = any(len(s.segment_id) > 64 for s in segments)
    aliases = {
        s.segment_id: f"s-{i + 1}" if compact else s.segment_id
        for i, s in enumerate(segments)
    }
    by_id = {s.segment_id: s for s in segments}
    measured: list[dict[str, object]] = []
    for suggestion in proposal.suggestions:
        candidate = suggestion.candidate
        ids = set((*candidate.segment_ids, *candidate.context_segment_ids))
        pending = list(ids)
        while pending:
            for dep in by_id[pending.pop()].context_dependencies:
                if dep.segment_id not in ids:
                    ids.add(dep.segment_id)
                    pending.append(dep.segment_id)
        measured.append(
            {
                "title": candidate.title,
                "segment_ids": [
                    aliases[s.segment_id] for s in segments if s.segment_id in ids
                ],
                "duration_ms": sum(by_id[s].end_ms - by_id[s].start_ms for s in ids)
                + sum(
                    by_id[s].end_ms - by_id[s].start_ms
                    for s in suggestion.hook_segment_ids
                ),
            }
        )
    # Measured contiguous options help the model avoid arithmetic mistakes.
    # These are suggestions only, not automatically accepted editorial decisions.
    windows: list[dict[str, object]] = []
    if brief.min_ms is not None and brief.max_ms is not None:
        for start in range(0, len(segments), max(1, len(segments) // 12)):
            window_ids: list[str] = []
            duration = 0
            for segment in segments[start:]:
                duration += segment.end_ms - segment.start_ms
                if duration > brief.max_ms:
                    break
                window_ids.append(segment.segment_id)
                if duration >= brief.min_ms:
                    windows.append(
                        {
                            "segment_ids": [aliases[s] for s in window_ids],
                            "duration_ms_before_context": duration,
                        }
                    )
                    break
    return {
        "instruction": "这是唯一一次修订。上一方案不满足本地测量要求。重新选择更窄但完整的子主题，可少返回；不要重复超限方案。measured_windows仅供选材，先检查语义与必要背景，允许改选。时长包含实际背景；若不能满足则空返回说明。不要截断源句、丢否定/限定、生成语音或放宽brief。",
        "measured_candidates": measured,
        "local_notes": notes,
        "measured_windows": windows,
    }


async def plan_highlights(
    planner: HighlightPlanner,
    brief: HighlightBrief,
    segments: tuple[SemanticSegment, ...],
    asset_id: str,
    collection_id: str,
    *,
    previous: HighlightProposal | None = None,
    review_notes: tuple[str, ...] = (),
) -> HighlightWorkflowResult:
    segments = attach_continuation_context(segments)
    from minicut.chapter_planner import CHAPTER_CHAR_BUDGET, plan_chapters, source_size

    planning_segments = segments
    if previous is not None:
        proposal = previous
    elif source_size(segments) > CHAPTER_CHAR_BUDGET:
        proposal, planning_segments = await plan_chapters(planner, brief, segments)
    else:
        proposal = await planner.plan(brief, segments)
    selected = select_highlights(proposal, brief, segments, asset_id, collection_id)
    needs_revision = any(
        "时长超限" in n or "时长不足" in n or "源内容重复超过" in n
        for n in selected.notes
    )
    revised = False
    if review_notes or (
        needs_revision
        and (
            selected.collection is None or len(selected.collection.plans) < brief.count
        )
    ):
        proposal = await planner.plan(
            brief,
            planning_segments,
            revision=revision_feedback(
                proposal, brief, planning_segments, (*selected.notes, *review_notes)
            ),
        )
        selected = select_highlights(proposal, brief, segments, asset_id, collection_id)
        revised = True
    return HighlightWorkflowResult(proposal, selected, revised)
