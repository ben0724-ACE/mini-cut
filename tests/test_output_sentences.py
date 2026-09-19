from dataclasses import replace
from pathlib import Path

import pytest

from minicut.output_plan import OutputItem, OutputPlan, OutputRole
from minicut.output_sentences import split_output_sentences
from minicut.output_timeline import (
    build_output_cues,
    coalesce_output_media,
    compile_output_timeline,
)
from minicut.sentence_boundaries import sentence_segments
from minicut.transcript import Transcript, TranscriptSource, Word


def test_sentence_edits_preserve_every_millisecond_and_compact_gaps() -> None:
    transcript = Transcript(
        "t",
        TranscriptSource("a", "test", "test"),
        "zh",
        (
            Word("a", "第一句。", 100, 1000),
            Word("b", "第二句。", 3000, 4000),
            Word("c", "第三句。", 5000, 6000),
        ),
    )
    segments = sentence_segments(transcript)
    plan = OutputPlan(
        "video",
        "candidate",
        "title",
        (
            OutputItem(
                "body",
                segments[0].segment_id,
                OutputRole.BODY,
                source_start_ms=0,
                source_end_ms=6100,
            ),
        ),
    )
    divided = split_output_sentences(plan, segments, transcript)
    timeline = compile_output_timeline(divided, segments, "a")
    assert [
        (c.source_range.start_ms, c.source_range.end_ms) for c in timeline.clips
    ] == [(0, 3000), (3000, 5000), (5000, 6100)]
    assert timeline.estimated_duration_ms == 6100
    merged = coalesce_output_media(timeline, divided)
    assert len(merged.clips) == 1
    assert merged.clips[0].source_range.duration_ms == 6100
    compact = replace(
        plan,
        items=(
            replace(plan.items[0], source_end_ms=1000),
            OutputItem("last", segments[-1].segment_id, OutputRole.BODY),
        ),
    )
    divided = split_output_sentences(compact, segments, transcript)
    assert compile_output_timeline(divided, segments, "a").estimated_duration_ms == 2000
    assert (
        len(
            coalesce_output_media(
                compile_output_timeline(divided, segments, "a"), divided
            ).clips
        )
        == 2
    )


def test_corrected_long_caption_is_paginated_instead_of_filling_screen() -> None:
    transcript = Transcript(
        "t", TranscriptSource("a", "test", "test"), "zh", (Word("a", "原文", 0, 10000),)
    )
    segments = sentence_segments(transcript)
    text = "这是非常长的人工校正字幕" * 12
    plan = OutputPlan(
        "v",
        "c",
        "title",
        (OutputItem("i", segments[0].segment_id, OutputRole.BODY, display_text=text),),
    )
    timeline = compile_output_timeline(plan, segments, "a")
    cues = build_output_cues(timeline, plan, ())
    assert len(cues) > 1
    assert all(len(c.text.splitlines()) <= 2 for c in cues)
    assert "".join(c.text.replace("\n", "") for c in cues) == text
    assert cues[0].start_ms == 0 and cues[-1].end_ms == 10000


@pytest.mark.parametrize("manual", [False, True])
def test_split_existing_output_creates_one_revision_and_rejects_stale_save(
    tmp_path: Path,
    manual: bool,
) -> None:
    import asyncio
    import json

    import httpx

    from minicut.api import create_app
    from minicut.media import MediaAsset
    from minicut.output_plan import HighlightCandidate, OutputCollection
    from minicut.output_repository import OutputCollectionRepository
    from minicut.project import ProjectManifest, ProjectRepository

    project = tmp_path / "demo"
    ProjectRepository(project).create(
        ProjectManifest(
            "demo", (MediaAsset("a", "/original.mp4", 4000, (), "fixture"),)
        )
    )
    transcript = Transcript(
        "t",
        TranscriptSource("a", "test", "test"),
        "zh",
        (Word("a", "一句。", 0, 1000), Word("b", "二句。", 2000, 4000)),
    )
    segments = sentence_segments(transcript)
    path = project / ".minicut/transcripts/a.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"transcript": transcript.to_dict()}))
    repo = OutputCollectionRepository(project, "collection")
    repo.write_segments(segments)
    plan = OutputPlan(
        "video",
        "c",
        "title",
        (
            OutputItem(
                "i",
                segments[0].segment_id,
                OutputRole.BODY,
                display_text="已校正",
                source_start_ms=0,
                source_end_ms=4000,
            ),
        ),
    )
    repo.write(
        OutputCollection(
            "collection",
            "a",
            (
                HighlightCandidate(
                    "c", "title", "reason", tuple(s.segment_id for s in segments)
                ),
            ),
            (plan,),
        ),
        segments,
    )
    repo.write_highlight_result({"asset_id": "a", "outputs": [{"output_id": "video"}]})

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(tmp_path)),
            base_url="http://test",
        ) as client:
            url = "/api/projects/demo/highlights/collection/outputs/video/split-sentences?base_revision=1"
            body: dict[str, object] = {}
            if manual:
                url = "/api/projects/demo/highlights/collection/outputs/video/items/i/split"
                body = {
                    "base_revision": 1,
                    "lines": ["一句。", "二句。"],
                    "apply": False,
                }
                preview = await client.post(url, json=body)
                assert preview.status_code == 200
                assert preview.json()["ranges"][0]["end_ms"] == 2000
                assert repo.read(segments).plans[0].revision == 1
                body["apply"] = True
            response = await client.post(url, json=body)
            assert response.status_code == 200
            output = response.json()["outputs"][0]
            assert output["revision"] == 2
            assert len(output["clips"]) == 2
            assert output["duration_ms"] == 4000
            assert output["clips"][0]["text"] == "一句。"
            assert (await client.post(url, json=body)).status_code == 409
            assert not (project / "exports").exists()

    asyncio.run(run())
