"""Web-facing orchestration reusing the source-bound highlight workflow."""

import asyncio
import json
import os
from dataclasses import replace
from pathlib import Path
from typing import cast

from minicut.deepseek_provider import DeepSeekProvider
from minicut.errors import UserInputError
from minicut.highlight_brief import HighlightBrief
from minicut.highlight_planner import HighlightPlanner
from minicut.highlight_workflow import attach_continuation_context, plan_highlights
from minicut.output_plan import OutputRole
from minicut.output_repository import OutputCollectionRepository
from minicut.output_timeline import compile_output_timeline
from minicut.segmentation import build_utterances
from minicut.semantic_segment import SemanticSegment
from minicut.semantic_segmentation import (
    build_rule_based_segments,
    mark_segment_candidates,
)
from minicut.text_normalization import normalize_transcript_words
from minicut.transcript import Transcript


def generate_highlights(
    project: Path, asset_id: str, collection_id: str, brief: HighlightBrief
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
    utterances = transcript.utterances or build_utterances(
        transcript, normalize_transcript_words(transcript)
    )
    segments = attach_continuation_context(
        mark_segment_candidates(build_rule_based_segments(transcript, utterances))
    )
    planner = HighlightPlanner(
        DeepSeekProvider(
            key,
            base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        ),
        model=os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash"),
    )
    workflow = asyncio.run(
        plan_highlights(planner, brief, segments, asset_id, collection_id)
    )
    selection = workflow.selection
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
                    "duration_ms": timeline.estimated_duration_ms,
                    "clips": [
                        {
                            "instance_id": item.instance_id,
                            "segment_id": item.segment_id,
                            "role": item.role.value,
                            "text": by_id[item.segment_id].text,
                            "start_ms": by_id[item.segment_id].start_ms,
                            "end_ms": by_id[item.segment_id].end_ms,
                        }
                        for item in plan.items
                    ],
                }
            )
    result: dict[str, object] = {
        "collection_id": collection_id,
        "asset_id": asset_id,
        "brief": brief.to_dict(),
        "notes": list(selection.notes),
        "outputs": outputs,
    }
    repository.write_highlight_result(result)
    return result


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
        if repository.path.is_file():
            segments = source_segments(project, cast(str, result["asset_id"]))
            collection = repository.read(segments)
            by_id = {segment.segment_id: segment for segment in segments}
            rows = {
                row["output_id"]: row
                for row in cast(list[dict[str, object]], result["outputs"])
            }
            for plan in collection.plans:
                row = rows[plan.output_id]
                row["revision"] = plan.revision
                row["duration_ms"] = compile_output_timeline(
                    plan, segments, collection.asset_id
                ).estimated_duration_ms
                row["clips"] = [
                    {
                        "instance_id": item.instance_id,
                        "segment_id": item.segment_id,
                        "role": item.role.value,
                        "text": item.display_text or by_id[item.segment_id].text,
                        "source_text": by_id[item.segment_id].text,
                        "deleted": item.deleted,
                        "start_ms": by_id[item.segment_id].start_ms,
                        "end_ms": by_id[item.segment_id].end_ms,
                    }
                    for item in plan.items
                ]
        return result
    except (OSError, ValueError) as error:
        raise UserInputError("Highlight result is missing or invalid") from error


def source_segments(project: Path, asset: str) -> tuple[SemanticSegment, ...]:
    try:
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
) -> dict[str, object]:
    result = read_highlights(project, collection_id)
    segments = source_segments(project, cast(str, result["asset_id"]))
    repository = OutputCollectionRepository(project, collection_id)
    collection = repository.read(segments)
    plan = next(
        (plan for plan in collection.plans if plan.output_id == output_id), None
    )
    if plan is None or not any(item.instance_id == instance_id for item in plan.items):
        raise UserInputError("Output item does not exist")
    updated = replace(
        plan,
        revision=plan.revision + 1,
        items=tuple(
            replace(
                item,
                deleted=item.deleted if deleted is None else deleted,
                display_text=item.display_text
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
) -> dict[str, object]:
    result = read_highlights(project, collection_id)
    segments = source_segments(project, cast(str, result["asset_id"]))
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
    updated = replace(
        plan,
        revision=plan.revision + 1,
        items=tuple(
            replace(by_id[identity], role=OutputRole(roles[identity]))
            if identity in roles
            else by_id[identity]
            for identity in order
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


def output_versions(
    project: Path, collection_id: str, output_id: str
) -> list[dict[str, object]]:
    result = read_highlights(project, collection_id)
    segments = source_segments(project, cast(str, result["asset_id"]))
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
    return [
        {
            "revision": plan.revision,
            "duration_ms": compile_output_timeline(
                plan, segments, cast(str, result["asset_id"])
            ).estimated_duration_ms,
            "clips": [
                {
                    "instance_id": item.instance_id,
                    "segment_id": item.segment_id,
                    "role": item.role.value,
                    "deleted": item.deleted,
                    "text": item.display_text or by_id[item.segment_id].text,
                    "start_ms": by_id[item.segment_id].start_ms,
                    "end_ms": by_id[item.segment_id].end_ms,
                }
                for item in plan.items
            ],
        }
        for plan in sorted(plans, key=lambda plan: plan.revision)
    ]
