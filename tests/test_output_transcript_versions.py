import json
import shutil
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Lock
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from minicut.application import TranscribeProjectUseCase, TranscribeRequest
from minicut.errors import ProcessingError, UserInputError
from minicut.highlight_brief import HighlightBrief, HighlightPreset
from minicut.highlight_service import (
    generate_highlights,
    manual_split_output,
    output_versions,
    read_highlights,
    rename_output,
    save_output_ranges,
    source_segments,
    split_saved_output,
    translate_output_subtitles,
)
from minicut.media import MediaAsset, StreamInfo, StreamType
from minicut.output_export import export_output, preview_output
from minicut.output_plan import (
    HighlightCandidate,
    OutputCollection,
    OutputItem,
    OutputPlan,
    OutputRole,
)
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
from minicut.transcription_task import CancellationToken


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
    translate_output_subtitles(
        workspace.project, "collection", "range", 1, "zh", Lock()
    )
    assert translator.call_args.args[2] == workspace.old


def test_generation_retry_retains_initial_transcript(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-no-network")
    planner = AsyncMock(side_effect=ProcessingError("interrupted"))
    monkeypatch.setattr("minicut.highlight_service.plan_highlights", planner)
    brief = HighlightBrief(HighlightPreset.KNOWLEDGE, 1, None, None)
    with pytest.raises(ProcessingError, match="interrupted"):
        generate_highlights(workspace.project, "asset", "pending", brief)
    workspace.retranscribe()
    with pytest.raises(ProcessingError, match="interrupted"):
        generate_highlights(workspace.project, "asset", "pending", brief)
    assert planner.call_args_list[0].args[2] == planner.call_args_list[1].args[2]
    assert (
        OutputCollectionRepository(workspace.project, "pending").source_transcript(
            "asset"
        )
        == workspace.old
    )


def test_missing_bound_version_never_falls_back_to_latest(workspace: Workspace) -> None:
    workspace.retranscribe()
    binding = json.loads(
        workspace.repository.path.with_suffix(".transcript.json").read_text()
    )
    TranscriptVersionRepository(workspace.project, "asset").version_path(
        binding["transcript_version"]
    ).unlink()
    with pytest.raises(UserInputError, match="version is missing or invalid"):
        read_highlights(workspace.project, "collection")


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
