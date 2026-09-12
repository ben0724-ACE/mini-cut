"""Measured selection, context closure and explicit whole-segment composition."""

from dataclasses import dataclass, replace

from minicut.highlight_brief import HighlightBrief
from minicut.highlight_planner import HighlightProposal
from minicut.output_plan import (
    HighlightCandidate,
    OutputCollection,
    OutputItem,
    OutputPlan,
    OutputRole,
    validate_output_collection,
)
from minicut.semantic_segment import (
    SemanticSegment,
    validate_segment_context_dependencies,
)


def _union(ranges: tuple[tuple[int, int], ...]) -> tuple[tuple[int, int], ...]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return tuple(merged)


def source_overlap(
    left: tuple[tuple[int, int], ...], right: tuple[tuple[int, int], ...]
) -> float:
    a, b = _union(left), _union(right)
    shorter = min(sum(e - s for s, e in a), sum(e - s for s, e in b))
    intersection = sum(
        max(0, min(ae, be) - max(as_, bs)) for as_, ae in a for bs, be in b
    )
    return intersection / shorter if shorter else 0.0


@dataclass(frozen=True, slots=True)
class HighlightSelection:
    collection: OutputCollection | None
    notes: tuple[str, ...]
    durations_ms: tuple[int, ...]


def select_highlights(
    proposal: HighlightProposal,
    brief: HighlightBrief,
    segments: tuple[SemanticSegment, ...],
    asset_id: str,
    collection_id: str,
) -> HighlightSelection:
    validate_segment_context_dependencies(segments)
    by_id = {s.segment_id: s for s in segments}
    candidates: list[HighlightCandidate] = []
    plans: list[OutputPlan] = []
    ranges: list[tuple[tuple[int, int], ...]] = []
    durations: list[int] = []
    notes = list(proposal.notes)
    for suggestion in proposal.suggestions:
        candidate = suggestion.candidate
        selected = set((*candidate.segment_ids, *candidate.context_segment_ids))
        if (
            not selected <= by_id.keys()
            or not set(suggestion.hook_segment_ids) <= selected
        ):
            raise ValueError("candidate references unknown source")
        pending = list(selected)
        while pending:
            for dependency in by_id[pending.pop()].context_dependencies:
                if dependency.segment_id not in selected:
                    selected.add(dependency.segment_id)
                    pending.append(dependency.segment_id)
        body = sorted(
            (by_id[s] for s in selected), key=lambda s: (s.start_ms, s.end_ms)
        )
        source_ranges = tuple((s.start_ms, s.end_ms) for s in body)
        hook = suggestion.hook_segment_ids
        if hook and brief.hook_ms is None:
            raise ValueError("hook was disabled")
        hook_duration = sum(by_id[s].end_ms - by_id[s].start_ms for s in hook)
        duration = sum(s.end_ms - s.start_ms for s in body) + hook_duration
        if brief.min_ms is not None and duration < brief.min_ms:
            notes.append(
                f"{candidate.title}：时长不足（{duration} ms），不填充无关内容。"
            )
            continue
        if brief.max_ms is not None and duration > brief.max_ms:
            notes.append(
                f"{candidate.title}：时长超限（{duration} ms），保留完整语义，不盲目截断。"
            )
            continue
        if any(
            source_overlap(source_ranges, previous) > brief.max_source_overlap
            for previous in ranges
        ):
            notes.append(
                f"{candidate.title}：源内容重复超过 {brief.max_source_overlap:.0%}，未入选。"
            )
            continue
        if brief.hook_ms is not None:
            if not hook:
                notes.append(f"{candidate.title}：未找到独立原话钩子，保留正文。")
            elif abs(hook_duration - brief.hook_ms) > 2000:
                notes.append(
                    f"{candidate.title}：钩子 {hook_duration} ms，完整原话优先，不强切至五秒。"
                )
            if any(by_id[s].context_dependencies for s in hook):
                notes.append(f"{candidate.title}：钩子含上下文依赖，请审阅限定条件。")
        extra = tuple(
            s.segment_id for s in body if s.segment_id not in candidate.segment_ids
        )
        candidates.append(replace(candidate, context_segment_ids=extra))
        output_id = f"video-{len(plans) + 1}"
        items = tuple(
            OutputItem(f"{output_id}-hook-{i}", s, OutputRole.HOOK)
            for i, s in enumerate(hook)
        ) + tuple(
            OutputItem(f"{output_id}-body-{i}", s.segment_id, OutputRole.BODY)
            for i, s in enumerate(body)
        )
        plans.append(
            OutputPlan(output_id, candidate.candidate_id, candidate.title, items)
        )
        durations.append(duration)
        ranges.append(source_ranges)
        if len(plans) == brief.count:
            break
    if len(plans) < brief.count:
        notes.append(f"数量不足：要求 {brief.count} 条，实际 {len(plans)} 条；未凑数。")
    collection = (
        OutputCollection(collection_id, asset_id, tuple(candidates), tuple(plans))
        if plans
        else None
    )
    if collection is not None:
        validate_output_collection(collection, segments)
    return HighlightSelection(collection, tuple(notes), tuple(durations))
