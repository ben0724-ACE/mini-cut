"""Web-facing orchestration reusing the source-bound highlight workflow."""

import asyncio
import json
import os
from dataclasses import replace
from pathlib import Path
from typing import cast

from minicut.boundary_refinement import refine_boundaries
from minicut.deepseek_provider import DeepSeekProvider
from minicut.errors import UserInputError
from minicut.highlight_brief import HighlightBrief
from minicut.highlight_planner import HighlightPlanner
from minicut.highlight_workflow import attach_continuation_context, plan_highlights
from minicut.model_journal import ModelJournal, RecordedProvider
from minicut.output_plan import OutputItem, OutputRole
from minicut.output_repository import OutputCollectionRepository
from minicut.output_timeline import compile_output_timeline
from minicut.project import ProjectRepository
from minicut.segmentation import build_utterances
from minicut.semantic_segment import SemanticSegment
from minicut.semantic_segmentation import (
    build_rule_based_segments,
    mark_segment_candidates,
)
from minicut.sentence_boundaries import sentence_segments
from minicut.text_normalization import normalize_text, normalize_transcript_words
from minicut.transcript import Transcript
from minicut.transcription_task import CancellationToken


def generate_highlights(
    project: Path,
    asset_id: str,
    collection_id: str,
    brief: HighlightBrief,
    *,
    cancellation: CancellationToken | None = None,
) -> dict[str, object]:
    try:
        cache = json.loads(
            (project / ".minicut/transcripts" / f"{asset_id}.json").read_text(
                encoding="utf-8"
            )
        )
        transcript = Transcript.from_dict(cache["transcript"])
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise UserInputError(
            "Transcription is required before generating highlights"
        ) from error
    if transcript.source.asset_id != asset_id:
        raise UserInputError("Transcript asset does not match")
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        raise UserInputError("DeepSeek is not configured on the server")
    segments = sentence_segments(transcript)
    repository = OutputCollectionRepository(project, collection_id)
    repository.write_segments(segments)
    recorded = RecordedProvider(
        DeepSeekProvider(
            key,
            base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        ),
        ModelJournal(project),
        cancellation,
    )
    planner = HighlightPlanner(
        recorded,
        model=os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash"),
        timeout=180,
    )
    workflow = asyncio.run(
        plan_highlights(planner, brief, segments, asset_id, collection_id)
    )
    duration_ms = next(
        a.duration_ms
        for a in ProjectRepository(project).read().assets
        if a.asset_id == asset_id
    )
    selection = asyncio.run(
        refine_boundaries(
            workflow.selection,
            brief,
            transcript,
            segments,
            recorded,
            planner.model,
            duration_ms,
        )
    )
    outputs: list[dict[str, object]] = []
    repository = OutputCollectionRepository(project, collection_id)
    if selection.collection is not None:
        repository.write(selection.collection, segments)
        candidates = {
            candidate.candidate_id: candidate
            for candidate in selection.collection.candidates
        }
        by_id = {segment.segment_id: segment for segment in segments}
        for plan in selection.collection.plans:
            timeline = compile_output_timeline(plan, segments, asset_id)
            outputs.append(
                {
                    "output_id": plan.output_id,
                    "title": plan.title,
                    "reason": candidates[plan.candidate_id].reason,
                    "revision": plan.revision,
                    "hook_transition_ms": plan.hook_transition_ms,
                    "hook_transition_kind": plan.hook_transition_kind,
                    "duration_ms": timeline.estimated_duration_ms,
                    "clips": [
                        {
                            "instance_id": item.instance_id,
                            "segment_id": item.segment_id,
                            "role": item.role.value,
                            "text": by_id[item.segment_id].text,
                            "start_ms": item.source_start_ms
                            if item.source_start_ms is not None
                            else by_id[item.segment_id].start_ms,
                            "end_ms": item.source_end_ms
                            if item.source_end_ms is not None
                            else by_id[item.segment_id].end_ms,
                        }
                        for item in plan.items
                    ],
                }
            )
    result: dict[str, object] = {
        "collection_id": collection_id,
        "asset_id": asset_id,
        "brief": brief.to_dict(),
        "source_duration_ms": duration_ms,
        "notes": list(selection.notes),
        "outputs": outputs,
        "model_requests": recorded.receipts,
    }
    repository.write_highlight_result(result)
    return read_highlights(project, collection_id)


def read_highlights(project: Path, collection_id: str) -> dict[str, object]:
    repository = OutputCollectionRepository(project, collection_id)
    try:
        result = cast(
            dict[str, object],
            json.loads(
                (
                    project / ".minicut/highlight-results" / f"{collection_id}.json"
                ).read_text(encoding="utf-8")
            ),
        )
        if "source_duration_ms" not in result:
            duration = next(
                (
                    a.duration_ms
                    for a in ProjectRepository(project).read().assets
                    if a.asset_id == result["asset_id"]
                ),
                None,
            )
            if duration is not None:
                result["source_duration_ms"] = duration
        if repository.path.is_file():
            segments = source_segments(
                project, cast(str, result["asset_id"]), collection_id
            )
            collection = repository.read(segments)
            by_id = {segment.segment_id: segment for segment in segments}
            rows = {
                row["output_id"]: row
                for row in cast(list[dict[str, object]], result["outputs"])
            }
            for plan in collection.plans:
                row = rows[plan.output_id]
                row["revision"] = plan.revision
                row["hook_transition_ms"] = plan.hook_transition_ms
                row["hook_transition_kind"] = plan.hook_transition_kind
                row["duration_ms"] = compile_output_timeline(
                    plan, segments, collection.asset_id
                ).estimated_duration_ms
                transcript = _source_transcript(project, collection.asset_id)
                row["clips"] = [
                    {
                        "instance_id": item.instance_id,
                        "segment_id": item.segment_id,
                        "role": item.role.value,
                        "text": item.display_text
                        or _item_text(item, by_id[item.segment_id], transcript),
                        "source_text": by_id[item.segment_id].text,
                        "deleted": item.deleted,
                        "start_ms": item.source_start_ms
                        if item.source_start_ms is not None
                        else by_id[item.segment_id].start_ms,
                        "end_ms": item.source_end_ms
                        if item.source_end_ms is not None
                        else by_id[item.segment_id].end_ms,
                    }
                    for item in plan.items
                ]
        return result
    except (OSError, ValueError) as error:
        raise UserInputError("Highlight result is missing or invalid") from error


def source_segments(
    project: Path, asset: str, collection_id: str | None = None
) -> tuple[SemanticSegment, ...]:
    try:
        if collection_id is not None:
            snapshot = OutputCollectionRepository(
                project, collection_id
            ).path.with_suffix(".segments.json")
            if snapshot.is_file():
                return tuple(
                    SemanticSegment.from_dict(row)
                    for row in json.loads(snapshot.read_text(encoding="utf-8"))
                )
        cache = json.loads(
            (project / ".minicut/transcripts" / f"{asset}.json").read_text(
                encoding="utf-8"
            )
        )
        transcript = Transcript.from_dict(cache["transcript"])
        utterances = transcript.utterances or build_utterances(
            transcript, normalize_transcript_words(transcript)
        )
        return attach_continuation_context(
            mark_segment_candidates(build_rule_based_segments(transcript, utterances))
        )
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise UserInputError("Source transcript is missing or invalid") from error


def edit_output_item(
    project: Path,
    collection_id: str,
    output_id: str,
    instance_id: str,
    *,
    deleted: bool | None = None,
    display_text: str | None = None,
    source_start_ms: int | None = None,
    source_end_ms: int | None = None,
) -> dict[str, object]:
    result = read_highlights(project, collection_id)
    segments = source_segments(project, cast(str, result["asset_id"]), collection_id)
    repository = OutputCollectionRepository(project, collection_id)
    collection = repository.read(segments)
    plan = next(
        (plan for plan in collection.plans if plan.output_id == output_id), None
    )
    if plan is None or not any(item.instance_id == instance_id for item in plan.items):
        raise UserInputError("Output item does not exist")
    if source_start_ms is not None or source_end_ms is not None:
        asset = next(
            a
            for a in ProjectRepository(project).read().assets
            if a.asset_id == collection.asset_id
        )
        if (
            source_start_ms is None
            or source_end_ms is None
            or not 0 <= source_start_ms < source_end_ms <= asset.duration_ms
        ):
            raise UserInputError("起止时间必须位于源素材内，且结束晚于开始")
    updated = replace(
        plan,
        revision=plan.revision + 1,
        items=tuple(
            replace(
                item,
                deleted=item.deleted if deleted is None else deleted,
                source_start_ms=item.source_start_ms
                if source_start_ms is None
                else source_start_ms,
                source_end_ms=item.source_end_ms
                if source_end_ms is None
                else source_end_ms,
                display_text=(
                    None if source_start_ms is not None else item.display_text
                )
                if display_text is None
                else display_text.strip(),
            )
            if item.instance_id == instance_id
            else item
            for item in plan.items
        ),
    )
    repository.write(
        replace(
            collection,
            plans=tuple(
                updated if existing.output_id == output_id else existing
                for existing in collection.plans
            ),
        ),
        segments,
    )
    return read_highlights(project, collection_id)


def reorder_output(
    project: Path,
    collection_id: str,
    output_id: str,
    order: list[str],
    roles: dict[str, str],
    hook_transition_ms: int | None = None,
    hook_transition_kind: str | None = None,
) -> dict[str, object]:
    result = read_highlights(project, collection_id)
    segments = source_segments(project, cast(str, result["asset_id"]), collection_id)
    repository = OutputCollectionRepository(project, collection_id)
    collection = repository.read(segments)
    plan = next(
        (plan for plan in collection.plans if plan.output_id == output_id), None
    )
    if plan is None:
        raise UserInputError("Output does not exist")
    by_id = {item.instance_id: item for item in plan.items}
    if (
        len(order) != len(by_id)
        or set(order) != set(by_id)
        or not set(roles) <= set(by_id)
    ):
        raise UserInputError("Order must contain every instance exactly once")
    promoted = {
        identity
        for identity, role in roles.items()
        if role == "hook" and by_id[identity].role is OutputRole.BODY
    }
    if any(by_id[identity].deleted for identity in promoted):
        raise UserInputError("Restore the body excerpt before adding an opening hook")
    arranged: list[OutputItem] = []
    for identity in order:
        item = by_id[identity]
        target = OutputRole(roles.get(identity, item.role.value))
        if identity in promoted:
            arranged.append(
                replace(
                    item,
                    instance_id=f"{identity}-hook-v{plan.revision + 1}",
                    role=OutputRole.HOOK,
                )
            )
        elif (
            item.role is OutputRole.HOOK
            and target is OutputRole.BODY
            and any(
                other.role is OutputRole.BODY and other.segment_id == item.segment_id
                for other in plan.items
            )
        ):
            continue  # Removing the teaser leaves its existing body occurrence intact.
        else:
            arranged.append(replace(item, role=target))
    if promoted:
        hooks = [item for item in arranged if item.role is OutputRole.HOOK]
        # Promoting a teaser must not reorder or remove the complete body.
        body = [item for item in plan.items if item.role is OutputRole.BODY]
        arranged = hooks + body
    updated = replace(
        plan,
        revision=plan.revision + 1,
        items=tuple(arranged),
        hook_transition_kind=plan.hook_transition_kind
        if hook_transition_kind is None
        else hook_transition_kind,
        hook_transition_ms=plan.hook_transition_ms
        if hook_transition_ms is None
        else hook_transition_ms,
    )
    repository.write(
        replace(
            collection,
            plans=tuple(
                updated if existing.output_id == output_id else existing
                for existing in collection.plans
            ),
        ),
        segments,
    )
    return read_highlights(project, collection_id)


def output_versions(
    project: Path, collection_id: str, output_id: str
) -> list[dict[str, object]]:
    result = read_highlights(project, collection_id)
    segments = source_segments(project, cast(str, result["asset_id"]), collection_id)
    repository = OutputCollectionRepository(project, collection_id)
    current = next(
        (
            plan
            for plan in repository.read(segments).plans
            if plan.output_id == output_id
        ),
        None,
    )
    if current is None:
        raise UserInputError("Output does not exist")
    from minicut.output_plan import OutputPlan

    plans = [
        OutputPlan.from_dict(json.loads(path.read_text(encoding="utf-8")))
        for path in repository.version_path(output_id, 1).parent.glob("*.json")
    ]
    plans = [plan for plan in plans if plan.revision < current.revision] + [current]
    by_id = {segment.segment_id: segment for segment in segments}
    transcript = _source_transcript(project, cast(str, result["asset_id"]))
    return [
        {
            "revision": plan.revision,
            "hook_transition_ms": plan.hook_transition_ms,
            "hook_transition_kind": plan.hook_transition_kind,
            "duration_ms": compile_output_timeline(
                plan, segments, cast(str, result["asset_id"])
            ).estimated_duration_ms,
            "clips": [
                {
                    "instance_id": item.instance_id,
                    "segment_id": item.segment_id,
                    "role": item.role.value,
                    "deleted": item.deleted,
                    "text": item.display_text
                    or _item_text(item, by_id[item.segment_id], transcript),
                    "start_ms": item.source_start_ms
                    if item.source_start_ms is not None
                    else by_id[item.segment_id].start_ms,
                    "end_ms": item.source_end_ms
                    if item.source_end_ms is not None
                    else by_id[item.segment_id].end_ms,
                }
                for item in plan.items
            ],
        }
        for plan in sorted(plans, key=lambda plan: plan.revision)
    ]


def _source_transcript(project: Path, asset_id: str) -> Transcript:
    data = json.loads(
        (project / ".minicut/transcripts" / f"{asset_id}.json").read_text(
            encoding="utf-8"
        )
    )
    return Transcript.from_dict(data["transcript"])


def _item_text(
    item: OutputItem, segment: SemanticSegment, transcript: Transcript
) -> str:
    if item.source_start_ms is None or item.source_end_ms is None:
        return segment.text
    return (
        normalize_text(
            " ".join(
                w.text
                for w in transcript.words
                if w.start_ms < item.source_end_ms and w.end_ms > item.source_start_ms
            )
        )
        or "（此范围无转录文字）"
    )


class RevisionConflict(UserInputError):
    """The editor must reload before overwriting a newer revision."""


def save_output_ranges(
    project: Path,
    collection_id: str,
    output_id: str,
    base_revision: int,
    ranges: list[dict[str, object]],
) -> dict[str, object]:
    # Serialize with other edits in the API; replace the collection only once.
    result = read_highlights(project, collection_id)
    asset_id = cast(str, result["asset_id"])
    segments = source_segments(project, asset_id, collection_id)
    repository = OutputCollectionRepository(project, collection_id)
    collection = repository.read(segments)
    plan = next((p for p in collection.plans if p.output_id == output_id), None)
    if plan is None:
        raise UserInputError("作品不存在")
    if plan.revision != base_revision:
        raise RevisionConflict("作品已有新版本，请刷新后重新调整；草稿尚未保存")
    duration = next(
        a.duration_ms
        for a in ProjectRepository(project).read().assets
        if a.asset_id == asset_id
    )
    changes = {cast(str, row["instance_id"]): row for row in ranges}
    if (
        not changes
        or len(changes) != len(ranges)
        or not changes.keys() <= {i.instance_id for i in plan.items}
    ):
        raise UserInputError("片段列表为空、重复或不存在")
    for row in ranges:
        start, end = row["source_start_ms"], row["source_end_ms"]
        if (
            type(start) is not int
            or type(end) is not int
            or not 0 <= start < end <= duration
        ):
            raise UserInputError("起止时间必须位于源素材内，且结束晚于开始")
    items = tuple(
        replace(
            item,
            source_start_ms=cast(int, changes[item.instance_id]["source_start_ms"]),
            source_end_ms=cast(int, changes[item.instance_id]["source_end_ms"]),
            display_text=None,
        )
        if item.instance_id in changes
        else item
        for item in plan.items
    )
    updated = replace(plan, revision=plan.revision + 1, items=items)
    repository.write(
        replace(
            collection,
            plans=tuple(
                updated if p.output_id == output_id else p for p in collection.plans
            ),
        ),
        segments,
    )
    return read_highlights(project, collection_id)
