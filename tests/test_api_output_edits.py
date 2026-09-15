import asyncio
import json
from pathlib import Path

import httpx

from minicut.api import create_app
from minicut.highlight_service import source_segments
from minicut.media import MediaAsset, StreamInfo, StreamType
from minicut.output_plan import (
    HighlightCandidate,
    OutputCollection,
    OutputItem,
    OutputPlan,
    OutputRole,
)
from minicut.output_repository import OutputCollectionRepository
from minicut.project import ProjectManifest, ProjectRepository
from minicut.transcript import Transcript, TranscriptSource, Word


def test_edit_preserves_source_and_other_output_and_rejects_empty_body(
    tmp_path: Path,
) -> None:
    project = tmp_path / "demo"
    ProjectRepository(project).create(
        ProjectManifest(
            "demo",
            (
                MediaAsset(
                    "asset",
                    str(project / "source.mp4"),
                    5000,
                    (
                        StreamInfo(0, StreamType.VIDEO, "h264"),
                        StreamInfo(1, StreamType.AUDIO, "aac"),
                    ),
                    "test",
                ),
            ),
        )
    )
    transcript = Transcript(
        "t",
        TranscriptSource("asset", "mlx", "large-v3-turbo"),
        "zh",
        (Word("w1", "第一句。", 0, 1000), Word("w2", "第二句。", 3000, 4000)),
    )
    path = project / ".minicut/transcripts/asset.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"transcript": transcript.to_dict()}))
    original = path.read_bytes()
    segments = source_segments(project, "asset")
    assert len(segments) == 2
    candidate = HighlightCandidate(
        "c", "测试", "完整", tuple(segment.segment_id for segment in segments)
    )
    items = tuple(
        OutputItem(f"i-{i}", segment.segment_id, OutputRole.BODY)
        for i, segment in enumerate(segments)
    )
    collection = OutputCollection(
        "collection",
        "asset",
        (candidate,),
        (
            OutputPlan("video-1", "c", "A", items),
            OutputPlan("video-2", "c", "B", items),
        ),
    )
    repository = OutputCollectionRepository(project, "collection")
    repository.write(collection, segments)
    repository.write_highlight_result(
        {
            "asset_id": "asset",
            "collection_id": "collection",
            "outputs": [{"output_id": "video-1"}, {"output_id": "video-2"}],
        }
    )

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(tmp_path)),
            base_url="http://test",
        ) as client:
            base = "/api/projects/demo/highlights/collection/outputs/video-1/items/"
            response = await client.patch(
                base + "i-0", json={"display_text": "术语更正", "deleted": True}
            )
            assert response.status_code == 200
            row = response.json()["outputs"][0]
            assert row["clips"][0]["segment_id"] == segments[0].segment_id
            assert row["clips"][0]["text"] == "术语更正"
            assert row["duration_ms"] == 1000
            assert (
                await client.patch(base + "i-1", json={"deleted": True})
            ).status_code == 400
            assert (
                await client.patch(base + "i-0", json={"deleted": False})
            ).status_code == 200
            output = "/api/projects/demo/highlights/collection/outputs/video-1"
            reordered = await client.put(
                output + "/order",
                json={
                    "order": ["i-1", "i-0"],
                    "roles": {"i-1": "hook"},
                    "hook_transition_ms": 150,
                },
            )
            assert reordered.status_code == 200
            assert reordered.json()["outputs"][0]["hook_transition_ms"] == 150
            assert (
                await client.put(
                    output + "/order", json={"order": [], "hook_transition_ms": 1001}
                )
            ).status_code == 422
            clips = reordered.json()["outputs"][0]["clips"]
            assert clips[0]["role"] == "hook"
            assert [clip["instance_id"] for clip in clips[1:]] == ["i-0", "i-1"]
            assert clips[0]["segment_id"] == clips[2]["segment_id"]
            assert reordered.json()["outputs"][0]["duration_ms"] == 3000
            removed = await client.put(
                output + "/order",
                json={
                    "order": ["i-0", "i-1", clips[0]["instance_id"]],
                    "roles": {clips[0]["instance_id"]: "body"},
                },
            )
            assert removed.status_code == 200
            assert [
                clip["instance_id"] for clip in removed.json()["outputs"][0]["clips"]
            ] == ["i-0", "i-1"]
            versions = (await client.get(output + "/versions")).json()
            assert len(versions) >= 3
            assert versions[-2]["clips"][0]["role"] == "hook"
            assert versions[-2]["hook_transition_ms"] == 150
            assert versions[-1]["hook_transition_ms"] == 150
            extended = await client.patch(
                base + "i-0", json={"source_start_ms": 500, "source_end_ms": 4000}
            )
            assert extended.status_code == 200
            updated_clip = extended.json()["outputs"][0]["clips"][0]
            assert updated_clip["start_ms"] == 500 and updated_clip["end_ms"] == 4000
            assert "第一句" in updated_clip["text"] and "第二句" in updated_clip["text"]
            assert (
                await client.patch(
                    base + "i-0", json={"source_start_ms": 0, "source_end_ms": 5001}
                )
            ).status_code == 400
            assert (
                await client.patch(base + "i-0", json={"source_start_ms": 0})
            ).status_code == 422
            kinds = await client.put(
                output + "/order",
                json={"order": ["i-0", "i-1"], "hook_transition_kind": "tv_static"},
            )
            assert kinds.status_code == 200
            assert kinds.json()["outputs"][0]["hook_transition_kind"] == "tv_static"

    asyncio.run(run())
    updated = repository.read(segments)
    assert updated.plans[1] == collection.plans[1]
    assert path.read_bytes() == original
