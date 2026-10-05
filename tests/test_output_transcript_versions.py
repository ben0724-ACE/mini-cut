import asyncio
import json
import shutil
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock

import httpx
import pytest

from minicut.api import create_app
from minicut.application import TranscribeProjectUseCase, TranscribeRequest
from minicut.cover_design import cover_context
from minicut.errors import ProcessingError, UserInputError
from minicut.highlight_brief import HighlightBrief
from minicut.highlight_selection import HighlightSelection
from minicut.highlight_service import (
    manual_split_output,
    output_versions,
    read_highlights,
    rename_output,
    save_output_ranges,
    source_segments,
    split_saved_output,
    translate_output_subtitles,
)
from minicut.llm_provider import TextModelRequest, TextModelResponse
from minicut.media import MediaAsset, StreamInfo, StreamType
from minicut.output_export import export_output, preview_output
from minicut.output_plan import (
    HighlightCandidate,
    OutputCollection,
    OutputItem,
    OutputPlan,
    OutputRole,
)
from minicut.output_reader import OutputReader
from minicut.output_render import OutputRenderRequest, RenderOutputUseCase
from minicut.output_repository import (
    OutputCollectionRepository,
    TranscriptVersionRepository,
)
from minicut.output_timeline import compile_output_timeline, map_output_words
from minicut.probe import probe_media
from minicut.project import ProjectManifest, ProjectRepository
from minicut.render_profile import RenderProfile
from minicut.sentence_boundaries import sentence_segments
from minicut.transcript import Transcript, TranscriptSource, Word
from minicut.transcription_task import CancellationToken, TranscriptionCancelled


@dataclass
class Workspace:
    project: Path
    request: TranscribeRequest
    use_case: TranscribeProjectUseCase
    old: Transcript
    new: Transcript
    repository: OutputCollectionRepository

    def retranscribe(self) -> None:
        result = self.use_case.execute(
            replace(self.request, model="small", language="zh")
        )
        assert not result.reused


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    source = tmp_path / "source.mp4"
    asset = MediaAsset(
        "asset",
        str(source),
        2500,
        (
            StreamInfo(0, StreamType.VIDEO, "h264"),
            StreamInfo(1, StreamType.AUDIO, "aac"),
        ),
        "fixture",
    )
    ProjectRepository(tmp_path).create(ProjectManifest("demo", (asset,)))
    # The recognizer's ID is not a unique transcription version.
    old = Transcript(
        "same-transcript-id",
        TranscriptSource("asset", "fixture", "tiny"),
        "en",
        (
            Word("old-1", "Old", 100, 450),
            Word("old-2", "speech.", 600, 1100),
            Word("old-3", "Still", 1400, 1650),
            Word("old-4", "here.", 1800, 2200),
        ),
    )
    new = Transcript(
        old.transcript_id,
        TranscriptSource("asset", "fixture", "small"),
        "zh",
        (Word("new-1", "全新转录内容。", 300, 1900),),
    )
    use_case = TranscribeProjectUseCase(
        importer=lambda repository, source_path: asset,
        transcriber=lambda asset, request: old if request.language == "en" else new,
    )
    request = TranscribeRequest(tmp_path, source, "mlx", "tiny", "en")
    use_case.execute(request)
    segments = sentence_segments(old)
    candidate = HighlightCandidate(
        "candidate", "Title", "Reason", tuple(s.segment_id for s in segments)
    )
    plan = OutputPlan(
        "range",
        "candidate",
        "Title",
        (
            OutputItem(
                "body",
                segments[0].segment_id,
                OutputRole.BODY,
                source_start_ms=0,
                source_end_ms=2300,
            ),
        ),
    )
    id_plan = replace(
        plan,
        output_id="ids",
        items=tuple(
            OutputItem(f"item-{i}", s.segment_id, OutputRole.BODY)
            for i, s in enumerate(segments)
        ),
    )
    repository = OutputCollectionRepository(tmp_path, "collection")
    repository.write_segments(segments)
    repository.write(
        OutputCollection("collection", "asset", (candidate,), (plan, id_plan)), segments
    )
    repository.write_highlight_result(
        {
            "collection_id": "collection",
            "asset_id": "asset",
            "outputs": [{"output_id": "range"}, {"output_id": "ids"}],
        }
    )
    return Workspace(tmp_path, request, use_case, old, new, repository)


@pytest.mark.parametrize("legacy", [False, True])
def test_retranscription_preserves_display_history_and_word_ids(
    workspace: Workspace, legacy: bool
) -> None:
    sources = TranscriptVersionRepository(workspace.project, "asset")
    before = None
    if legacy:
        # An unopened pre-upgrade collection must be protected before replacement.
        data = json.loads(sources.cache_path.read_text())
        data.pop("transcript_version")
        sources.cache_path.write_text(json.dumps(data))
    else:
        before = read_highlights(workspace.project, "collection")
    workspace.retranscribe()
    after = cast(dict[str, Any], read_highlights(workspace.project, "collection"))
    if before is not None:
        assert after == before
    assert after["outputs"][0]["revision"] == 1
    assert after["outputs"][0]["clips"][0]["text"] == "Old speech. Still here."
    assert workspace.repository.source_transcript("asset") == workspace.old
    segments = source_segments(workspace.project, "asset", "collection")
    plan = workspace.repository.read(segments).plans[1]
    mapped = map_output_words(
        compile_output_timeline(plan, segments, "asset"),
        plan,
        segments,
        "asset",
        workspace.repository.source_transcript("asset").words,
    )
    assert [w.word_id for w in mapped] == [w.word_id for w in workspace.old.words]
    rename_output(workspace.project, "collection", "range", 1, "Renamed")
    versions = cast(
        list[dict[str, Any]], output_versions(workspace.project, "collection", "range")
    )
    assert [v["revision"] for v in versions] == [1, 2]
    assert [v["clips"][0]["text"] for v in versions] == [
        "Old speech. Still here.",
        "Old speech. Still here.",
    ]
    new_repo = OutputCollectionRepository(workspace.project, "new-collection")
    assert new_repo.source_transcript("asset") == workspace.new
    new_version = sources.latest()[0]
    assert (
        json.loads(
            workspace.repository.path.with_suffix(".transcript.json").read_text()
        )["transcript_version"]
        != new_version
    )
    assert workspace.use_case.execute(
        replace(workspace.request, model="small", language="zh")
    ).reused
    assert sources.latest()[0] == new_version
    sources.cache_path.unlink()
    assert output_versions(workspace.project, "collection", "range") == versions
    assert workspace.repository.source_transcript("asset") == workspace.old


def test_range_edit_and_sentence_splits_use_bound_word_times(
    workspace: Workspace,
) -> None:
    workspace.retranscribe()
    parts = manual_split_output(
        workspace.project,
        "collection",
        "range",
        "body",
        1,
        ["Old speech.", "Still here."],
        False,
    )["ranges"]
    assert parts == [
        {"text": "Old speech.", "start_ms": 0, "end_ms": 1400},
        {"text": "Still here.", "start_ms": 1400, "end_ms": 2300},
    ]
    updated = save_output_ranges(
        workspace.project,
        "collection",
        "range",
        1,
        [{"instance_id": "body", "source_start_ms": 600, "source_end_ms": 2300}],
    )
    updated = cast(dict[str, Any], updated)
    assert updated["outputs"][0]["revision"] == 2
    assert updated["outputs"][0]["clips"][0]["text"] == "speech. Still here."
    split = cast(
        dict[str, Any], split_saved_output(workspace.project, "collection", "range", 2)
    )
    assert split["outputs"][0]["revision"] == 3
    assert [c["text"] for c in split["outputs"][0]["clips"]] == [
        "speech.",
        "Still here.",
    ]


def test_translation_uses_bound_source(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace.retranscribe()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-no-network")
    segments = source_segments(workspace.project, "asset", "collection")
    collection = workspace.repository.read(segments)
    translator = AsyncMock(
        return_value=replace(collection, plans=(collection.plans[0],))
    )
    monkeypatch.setattr("minicut.subtitle_translation.translate_collection", translator)
    translate_output_subtitles(workspace.project, "collection", "range", 1, "zh")
    assert translator.call_args.args[2] == workspace.old


@pytest.mark.parametrize("interrupted", ["failed", "cancelled"])
def test_api_resume_inherits_transcript_and_reuses_successful_model_response(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch, interrupted: str
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-no-network")
    model_inputs: list[list[str]] = []
    refinement_inputs: list[Transcript] = []

    class Provider:
        async def generate(self, request: TextModelRequest) -> TextModelResponse:
            payload = json.loads(request.user_prompt)
            model_inputs.append([s["text"] for s in payload["segments"]])
            candidate = payload["output_example"]["candidates"][0]
            candidate.update(
                segment_ids=[s["segment_id"] for s in payload["segments"]],
                context_segment_ids=[],
                hook_segment_ids=[],
            )
            return TextModelResponse(
                json.dumps({"candidates": [candidate], "notes": []}), request.model
            )

    async def refine(
        selection: HighlightSelection,
        brief: HighlightBrief,
        transcript: Transcript,
        *args: object,
    ) -> HighlightSelection:
        refinement_inputs.append(transcript)
        if len(refinement_inputs) <= 2:
            if interrupted == "cancelled":
                raise TranscriptionCancelled("interrupted")
            raise ProcessingError("interrupted")
        return selection

    def provider_factory(*args: object, **kwargs: object) -> Provider:
        return Provider()

    monkeypatch.setattr("minicut.highlight_service.DeepSeekProvider", provider_factory)
    monkeypatch.setattr("minicut.highlight_service.refine_boundaries", refine)

    async def run() -> None:
        app = create_app(workspace.project.parent, transcribe=workspace.use_case)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            base = f"/api/projects/{workspace.project.name}/tasks"
            assert (
                await client.post(
                    base + "/highlights",
                    json={
                        "asset_id": "asset",
                        "preset": "knowledge_digest",
                        "count": 1,
                    },
                    headers={"Idempotency-Key": "original"},
                )
            ).status_code == 202
            assert (await client.get(base + "/original")).json()[
                "status"
            ] == interrupted
            assert model_inputs == [["Old speech.", "Still here."]]
            original = OutputCollectionRepository(
                workspace.project, "highlights-original"
            )
            binding = original.path.with_suffix(".transcript.json").read_bytes()
            assert (
                await client.post(
                    base + "/transcribe",
                    json={
                        "asset_id": "asset",
                        "provider": "mlx",
                        "model": "small",
                        "language": "zh",
                    },
                    headers={"Idempotency-Key": "retranscribe"},
                )
            ).status_code == 202
            assert (await client.get(base + "/retranscribe")).json()[
                "status"
            ] == "succeeded"
            assert (
                TranscriptVersionRepository(workspace.project, "asset").latest()[1]
                == workspace.new
            )
            first = await client.post(base + "/original/resume")
            assert first.status_code == 202
            first_id = first.json()["task_id"]
            assert first_id != "original"
            assert (await client.get(base + f"/{first_id}")).json()[
                "status"
            ] == interrupted
            repeated = await client.post(base + "/original/resume")
            assert repeated.json()["task_id"] == first_id
            second = await client.post(base + f"/{first_id}/resume")
            assert second.status_code == 202
            second_id = second.json()["task_id"]
            assert second_id != first_id
            completed = (await client.get(base + f"/{second_id}")).json()
            assert completed["status"] == "succeeded"
            assert completed["result"]["model_requests"][0]["reused"] is True
            assert model_inputs == [["Old speech.", "Still here."]]
            assert refinement_inputs == [workspace.old] * 3
            for identity in (first_id, second_id):
                repository = OutputCollectionRepository(
                    workspace.project, f"highlights-{identity}"
                )
                assert (
                    repository.path.with_suffix(".transcript.json").read_bytes()
                    == binding
                )
                assert repository.source_transcript("asset") == workspace.old
            # A separate generation still starts from the newly transcribed data.
            assert (
                await client.post(
                    base + "/highlights",
                    json={
                        "asset_id": "asset",
                        "preset": "knowledge_digest",
                        "count": 1,
                    },
                    headers={"Idempotency-Key": "fresh"},
                )
            ).status_code == 202
            assert model_inputs[-1] == ["全新转录内容。"]

    asyncio.run(run())


def test_api_resume_rejects_missing_original_transcript_version(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-no-network")
    planner = AsyncMock(side_effect=ProcessingError("interrupted"))
    monkeypatch.setattr("minicut.highlight_service.plan_highlights", planner)

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(workspace.project.parent)),
            base_url="http://test",
        ) as client:
            base = f"/api/projects/{workspace.project.name}/tasks"
            assert (
                await client.post(
                    base + "/highlights",
                    json={
                        "asset_id": "asset",
                        "preset": "knowledge_digest",
                        "count": 1,
                    },
                    headers={"Idempotency-Key": "original"},
                )
            ).status_code == 202
            workspace.retranscribe()
            original = OutputCollectionRepository(
                workspace.project, "highlights-original"
            )
            binding = json.loads(
                original.path.with_suffix(".transcript.json").read_text()
            )
            TranscriptVersionRepository(workspace.project, "asset").version_path(
                binding["transcript_version"]
            ).unlink()
            response = await client.post(base + "/original/resume")
            assert response.status_code == 400
            assert (
                "Source transcript version is missing or invalid"
                in response.json()["detail"]
            )
            assert planner.call_count == 1
            assert not list((workspace.project / ".minicut/jobs").glob("resume-*.json"))

    asyncio.run(run())


@pytest.mark.parametrize(
    "consumer", ["display", "history", "preview", "cover", "export"]
)
def test_missing_bound_version_never_falls_back_to_latest(
    workspace: Workspace, consumer: str
) -> None:
    workspace.retranscribe()
    binding = json.loads(
        workspace.repository.path.with_suffix(".transcript.json").read_text()
    )
    TranscriptVersionRepository(workspace.project, "asset").version_path(
        binding["transcript_version"]
    ).unlink()
    with pytest.raises(UserInputError, match="version is missing or invalid"):
        if consumer == "display":
            read_highlights(workspace.project, "collection")
        elif consumer == "history":
            output_versions(workspace.project, "collection", "range")
        elif consumer == "preview":
            preview_output(
                workspace.project, "collection", "range", 1, CancellationToken()
            )
        elif consumer == "cover":
            cover_context(workspace.project, "collection", "range", 1)
        else:
            export_output(
                workspace.project,
                "collection",
                "range",
                "failed",
                1,
                "soft",
                0,
                "none",
                CancellationToken(),
            )


def test_reader_returns_saved_revision_with_its_full_original_source(
    workspace: Workspace,
) -> None:
    original = OutputReader(workspace.project, "collection").output("range", 1)
    rename_output(workspace.project, "collection", "range", 1, "Changed title")
    workspace.retranscribe()
    sources = TranscriptVersionRepository(workspace.project, "asset")
    sources.cache_path.unlink()
    reader = OutputReader(workspace.project, "collection")
    historical = reader.output("range", 1)
    current = reader.output("range")
    assert historical.plan == original.plan
    assert historical.source.transcript == current.source.transcript == workspace.old
    assert historical.source.segments == original.source.segments
    assert current.plan.revision == 2 and current.plan.title == "Changed title"
    assert [p.revision for p in reader.history("range").plans] == [1, 2]
    with pytest.raises(UserInputError, match="版本已变更"):
        reader.output("range", 1, require_current=True)


@pytest.mark.parametrize(
    "field", ["output_id", "revision", "candidate_id", "segment_id"]
)
@pytest.mark.parametrize("consumer", ["history", "preview", "render"])
def test_all_version_readers_reject_corrupt_history(
    workspace: Workspace, field: str, consumer: str
) -> None:
    rename_output(workspace.project, "collection", "range", 1, "New title")
    path = workspace.repository.version_path("range", 1)
    data = json.loads(path.read_text())
    if field == "segment_id":
        data["items"][0]["segment_id"] = "unknown-source"
    elif field == "revision":
        data[field] = 2
    else:
        data[field] = "other"
    path.write_text(json.dumps(data))
    with pytest.raises(
        UserInputError, match="Requested output version is missing or invalid"
    ):
        if consumer == "history":
            output_versions(workspace.project, "collection", "range")
        elif consumer == "preview":
            preview_output(
                workspace.project, "collection", "range", 1, CancellationToken()
            )
        else:
            source = OutputReader(workspace.project, "collection").read()
            RenderOutputUseCase().execute(
                OutputRenderRequest(
                    workspace.project,
                    "collection",
                    "range",
                    source.segments,
                    source.transcript,
                    plan_revision=1,
                )
            )


def test_failed_legacy_binding_does_not_replace_current_transcript(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    sources = TranscriptVersionRepository(workspace.project, "asset")
    before = sources.cache_path.read_bytes()
    writer = OutputCollectionRepository.write_json

    def fail_binding(path: Path, value: object) -> None:
        if path.name == "collection.transcript.json":
            raise ProcessingError("disk full")
        writer(path, value)

    monkeypatch.setattr(
        OutputCollectionRepository, "write_json", staticmethod(fail_binding)
    )
    with pytest.raises(ProcessingError, match="disk full"):
        workspace.retranscribe()
    assert sources.cache_path.read_bytes() == before


@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg required"
)
def test_real_exports_and_historical_preview_keep_original_subtitles(
    workspace: Workspace,
) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=blue:size=160x120:rate=25:duration=2.5",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=2.5",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(workspace.request.source_path),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    profile = RenderProfile(resolution=720)

    def render(output: str, export: str) -> bytes:
        export_output(
            workspace.project,
            "collection",
            output,
            export,
            1,
            "soft",
            0,
            "none",
            CancellationToken(),
            profile,
        )
        video = workspace.project / f"exports/collection/{output}/{export}/v0001.mp4"
        assert any(
            s.stream_type is StreamType.AUDIO for s in probe_media(video).streams
        )
        embedded = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(video),
                "-map",
                "0:s:0",
                "-f",
                "srt",
                "-",
            ],
            check=True,
            capture_output=True,
            timeout=30,
        ).stdout
        assert b"Old" in embedded and b"speech." in embedded
        return video.with_suffix(".srt").read_bytes()

    before = render("range", "before")
    preview = preview_output(
        workspace.project, "collection", "range", 1, CancellationToken()
    )
    workspace.retranscribe()
    assert render("range", "after") == before
    assert render("ids", "ids-after")
    cached = preview_output(
        workspace.project, "collection", "range", 1, CancellationToken()
    )
    assert cached["reused"] and cached["media_url"] == preview["media_url"]
    rename_output(workspace.project, "collection", "range", 1, "New title")
    from minicut.export_settings import PreviewOptions

    historical = preview_output(
        workspace.project,
        "collection",
        "range",
        1,
        CancellationToken(),
        PreviewOptions(audio_fade_ms=100),
    )
    assert not historical["reused"] and historical["revision"] == 1
    subtitle = (
        workspace.project
        / "exports"
        / cast(str, historical["subtitle_url"]).split("/media/exports/")[1]
    )
    assert subtitle.read_bytes() == before
