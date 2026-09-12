"""Web-facing orchestration reusing the source-bound highlight workflow."""

import asyncio
import json
import os
from pathlib import Path
from typing import cast

from minicut.deepseek_provider import DeepSeekProvider
from minicut.errors import UserInputError
from minicut.highlight_brief import HighlightBrief
from minicut.highlight_planner import HighlightPlanner
from minicut.highlight_workflow import attach_continuation_context, plan_highlights
from minicut.output_repository import OutputCollectionRepository
from minicut.output_timeline import compile_output_timeline
from minicut.segmentation import build_utterances
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
    OutputCollectionRepository(project, collection_id)
    try:
        return cast(
            dict[str, object],
            json.loads(
                (
                    project / ".minicut/highlight-results" / f"{collection_id}.json"
                ).read_text(encoding="utf-8")
            ),
        )
    except (OSError, ValueError) as error:
        raise UserInputError("Highlight result is missing or invalid") from error
