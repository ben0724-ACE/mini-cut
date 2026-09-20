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
from minicut.sentence_boundaries import complete_range


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
        continuous = brief.body_mode == "continuous"
        start, end, boundary_notes = complete_range(body, segments)
        end = min(end, max(s.end_ms for s in segments))
        if continuous:
            body = [s for s in segments if s.start_ms < end and s.end_ms > start]
            body.sort(key=lambda s: (s.start_ms, s.end_ms))
            notes.extend(f"{candidate.title}：{note}" for note in boundary_notes)
        source_ranges = (
            ((start, end),)
            if continuous
            else tuple((s.start_ms, s.end_ms) for s in body)
        )
        hook = suggestion.hook_segment_ids
        if hook and brief.hook_ms is None:
            raise ValueError("hook was disabled")
        hook_duration = 0
        if hook:
            ordered = sorted((by_id[s] for s in hook), key=lambda s: s.start_ms)
            first, last = ordered[0], ordered[-1]
            hook_duration = last.end_ms - first.start_ms
            between = {
                s.segment_id
                for s in segments
                if first.start_ms <= s.start_ms <= last.start_ms
            }
            low, high = brief.hook_bounds_ms
            if (
                not low <= hook_duration <= high
                or set(hook) != between
                or (
                    first.segment_id.startswith("sentence-v1-")
                    and "-s1-" not in first.segment_id
                )
                or (
                    last.segment_id.startswith("sentence-v1-")
                    and not last.segment_id.endswith("-e1")
                )
            ):
                reasons: list[str] = []
                if not low <= hook_duration <= high:
                    reasons.append(
                        f"实测 {hook_duration / 1000:g} 秒，不在允许的 {low / 1000:g}–{high / 1000:g} 秒范围内"
                    )
                if set(hook) != between:
                    reasons.append("引用并非相邻片段，中间遗漏原话")
                if (
                    first.segment_id.startswith("sentence-v1-")
                    and "-s1-" not in first.segment_id
                ) or (
                    last.segment_id.startswith("sentence-v1-")
                    and not last.segment_id.endswith("-e1")
                ):
                    reasons.append("首尾未落在可靠完整句边界")
                notes.append(
                    f"{candidate.title}：初选钩子未通过：{'；'.join(reasons)}。省略初选钩子，连续模式继续词级复核。"
                )
                hook = ()
                hook_duration = 0
            else:
                hook = tuple(s.segment_id for s in ordered)
        duration = sum(e - s for s, e in source_ranges) + hook_duration
        if brief.min_ms is not None and duration < brief.min_ms:
            notes.append(
                f"{candidate.title}：时长不足（{duration} ms），不填充无关内容。"
            )
        if brief.max_ms is not None and duration > brief.max_ms + min(
            brief.max_ms // 5, 15000
        ):
            notes.append(
                f"{candidate.title}：时长超限（{duration} ms），保留完整语义，不盲目截断。"
            )
            continue
        if brief.max_ms is not None and brief.max_ms < duration <= brief.max_ms + min(
            brief.max_ms // 5, 15000
        ):
            notes.append(f"{candidate.title}：为保留完整内容略超目标时长。")
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
                    f"{candidate.title}：钩子 {hook_duration} ms，完整原话优先，不强切至目标 {brief.hook_ms} ms。"
                )
            if any(by_id[s].context_dependencies for s in hook):
                notes.append(f"{candidate.title}：钩子含上下文依赖，请审阅限定条件。")
        extra = tuple(
            s.segment_id for s in body if s.segment_id not in candidate.segment_ids
        )
        candidates.append(replace(candidate, context_segment_ids=extra))
        output_id = f"video-{len(plans) + 1}"
        hook_items = (
            (
                OutputItem(
                    f"{output_id}-hook-0",
                    hook[0],
                    OutputRole.HOOK,
                    source_start_ms=by_id[hook[0]].start_ms,
                    source_end_ms=by_id[hook[-1]].end_ms,
                ),
            )
            if hook
            else ()
        )
        items = hook_items + tuple(
            OutputItem(f"{output_id}-body-{i}", s.segment_id, OutputRole.BODY)
            for i, s in enumerate(body)
        )
        if continuous:
            items = tuple(i for i in items if i.role is OutputRole.HOOK) + (
                OutputItem(
                    f"{output_id}-body-0",
                    body[0].segment_id,
                    OutputRole.BODY,
                    source_start_ms=start,
                    source_end_ms=end,
                ),
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
