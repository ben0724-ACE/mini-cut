"""Local real-media trial; credentials are read only from the environment."""

import argparse
import asyncio
import json
import os
from dataclasses import asdict
from pathlib import Path

import httpx

from minicut.application import TranscribeProjectUseCase, TranscribeRequest
from minicut.deepseek_provider import DeepSeekProvider
from minicut.highlight_brief import HighlightBrief, HighlightPreset
from minicut.highlight_planner import HighlightPlanner
from minicut.highlight_selection import select_highlights
from minicut.output_render import OutputRenderRequest, RenderOutputUseCase
from minicut.output_repository import OutputCollectionRepository
from minicut.segmentation import build_utterances
from minicut.semantic_segmentation import (
    build_rule_based_segments,
    mark_segment_candidates,
)
from minicut.text_normalization import normalize_transcript_words
from minicut.transcript import Transcript


def estimated_cost_cny(usage: dict[str, int], *, peak: bool = False) -> float:
    """2026-09-12 official Flash CNY prices; conservative peak optional."""
    hit = usage.get("prompt_cache_hit_tokens", 0)
    missed = usage.get("prompt_cache_miss_tokens", usage.get("prompt_tokens", 0) - hit)
    return (
        (hit * 0.02 + missed + usage.get("completion_tokens", 0) * 4)
        * (2 if peak else 1)
        / 1000000
    )


async def run(project: Path, asset_id: str, *, render_only: bool = False) -> None:
    cache = json.loads(
        (project / ".minicut/transcripts" / f"{asset_id}.json").read_text()
    )
    transcript = Transcript.from_dict(cache["transcript"])
    mappings = normalize_transcript_words(transcript)
    utterances = transcript.utterances or build_utterances(transcript, mappings)
    segments = mark_segment_candidates(
        build_rule_based_segments(transcript, utterances)
    )
    brief = HighlightBrief.for_preset(HighlightPreset.KNOWLEDGE)
    repo = OutputCollectionRepository(project, "knowledge-trial")
    report_path = project / "highlight-review.json"
    if not render_only:
        usage: dict[str, int] = {}

        async def record(response: httpx.Response) -> None:
            await response.aread()
            if response.is_success:
                body = response.json()
                usage.update(body.get("usage", {}))
                (project / "deepseek-trial-response.json").write_text(
                    json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8"
                )

        # Bound this paid short-media trial below the user-approved ¥1;
        # output is already limited to 4096 tokens by the existing adapter.
        size = (
            sum(
                len(s.text.encode("utf-8")) + len(s.segment_id.encode()) + 300
                for s in segments
            )
            + 10000
        )
        if (
            estimated_cost_cny(
                {"prompt_tokens": size, "completion_tokens": 4096}, peak=True
            )
            > 1
        ):
            raise ValueError("Trial exceeds approved budget; reduce trial input first")
        async with httpx.AsyncClient(
            base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            timeout=60,
            event_hooks={"response": [record]},
        ) as client:
            proposal = await HighlightPlanner(
                DeepSeekProvider(os.environ["DEEPSEEK_API_KEY"], client=client),
                model=os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash"),
            ).plan(brief, segments)
        selected = select_highlights(
            proposal, brief, segments, asset_id, "knowledge-trial"
        )
        report = {
            "brief": brief.to_dict(),
            "model": proposal.model,
            "prompt_version": proposal.prompt_version,
            "usage": usage,
            "cost_cny_peak_upper_estimate": estimated_cost_cny(usage, peak=True),
            "notes": selected.notes,
            "durations_ms": selected.durations_ms,
            "proposal": asdict(proposal),
            "outputs": [],
            "segments": [s.to_dict() for s in segments],
        }
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if selected.collection is None:
            print(
                json.dumps(
                    {"count": 0, "notes": selected.notes, "usage": usage},
                    ensure_ascii=False,
                )
            )
            return
        repo.write(selected.collection, segments)
    collection = repo.read(segments)
    report = json.loads(report_path.read_text())
    outputs: list[dict[str, object]] = []
    for plan in collection.plans:
        result = RenderOutputUseCase().execute(
            OutputRenderRequest(
                project,
                collection.collection_id,
                plan.output_id,
                segments,
                transcript,
                timeout_seconds=300,
            )
        )
        outputs.append(
            {
                "title": plan.title,
                "path": str(result.output_path),
                "duration_ms": result.timeline.estimated_duration_ms,
                "context_issues": [asdict(i) for i in result.context_issues],
            }
        )
        print(json.dumps(outputs[-1], ensure_ascii=False), flush=True)
    report["outputs"] = outputs
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "usage": report["usage"],
                "cost_cny_peak_upper_estimate": report["cost_cny_peak_upper_estimate"],
            },
            ensure_ascii=False,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("source", type=Path)
    parser.add_argument("--render-only", action="store_true")
    args = parser.parse_args()
    result = TranscribeProjectUseCase().execute(
        TranscribeRequest(
            args.project.resolve(), args.source.resolve(), "mlx", "large-v3-turbo", "zh"
        )
    )
    asyncio.run(
        run(args.project.resolve(), result.asset_id, render_only=args.render_only)
    )


if __name__ == "__main__":
    main()
