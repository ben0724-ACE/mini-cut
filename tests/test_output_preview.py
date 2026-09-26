import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import minicut.output_export as module
from minicut.errors import UserInputError
from minicut.highlight_service import source_segments
from minicut.media import MediaAsset, StreamInfo, StreamType
from minicut.output_export import export_output, preview_output
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
from minicut.transcription_task import CancellationToken


def test_preview_is_low_resolution_and_reuses_only_matching_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = MediaAsset(
        "asset",
        str(tmp_path / "source.webm"),
        4000,
        (StreamInfo(0, StreamType.VIDEO, "vp8"),),
        "existing",
    )
    ProjectRepository(tmp_path).create(ProjectManifest("demo", (asset,)))
    transcript = Transcript(
        "t",
        TranscriptSource("asset", "mlx", "model"),
        "en",
        (Word("w", "Hello.", 1000, 3000),),
    )
    cache = tmp_path / ".minicut/transcripts/asset.json"
    cache.parent.mkdir(parents=True)
    cache.write_text(json.dumps({"transcript": transcript.to_dict()}))
    segments = source_segments(tmp_path, "asset")
    plan = OutputPlan(
        "v", "c", "T", (OutputItem("i", segments[0].segment_id, OutputRole.BODY),)
    )
    repo = OutputCollectionRepository(tmp_path, "collection")
    repo.write(
        OutputCollection(
            "collection",
            "asset",
            (HighlightCandidate("c", "T", "R", (segments[0].segment_id,)),),
            (plan,),
        ),
        segments,
    )
    calls: list[object] = []

    def execute(self: object, request: module.OutputRenderRequest) -> object:
        calls.append(request)
        assert request.video_metadata.width <= 640
        output = (
            tmp_path / "exports/collection/v" / str(request.export_id) / "v0001.mp4"
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"video")
        subtitle = output.with_suffix(".srt")
        subtitle.write_text("Hello")
        repo.write_render_record("v", 1, {"plan": plan.to_dict()}, request.export_id)
        return SimpleNamespace(
            output_path=output,
            subtitle_path=subtitle,
            timeline=SimpleNamespace(estimated_duration_ms=2000),
        )

    def dimensions(path: Path) -> tuple[int, int]:
        return (1920, 1080)

    monkeypatch.setattr(module, "source_dimensions", dimensions)
    monkeypatch.setattr(module.RenderOutputUseCase, "execute", execute)
    first = preview_output(tmp_path, "collection", "v", 1, CancellationToken())
    second = preview_output(tmp_path, "collection", "v", 1, CancellationToken())
    assert first["revision"] == second["revision"] == 1
    assert second["reused"] is True and len(calls) == 1
    with pytest.raises(UserInputError):
        preview_output(tmp_path, "collection", "v", 2, CancellationToken())


def test_export_returns_publication_metadata_and_cover_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = MediaAsset(
        "asset",
        str(tmp_path / "source.webm"),
        4000,
        (StreamInfo(0, StreamType.VIDEO, "vp8"),),
        "existing",
    )
    ProjectRepository(tmp_path).create(ProjectManifest("demo", (asset,)))
    transcript = Transcript(
        "t",
        TranscriptSource("asset", "mlx", "model"),
        "zh",
        (Word("w", "内容。", 1000, 3000),),
    )
    cache = tmp_path / ".minicut/transcripts/asset.json"
    cache.parent.mkdir(parents=True)
    cache.write_text(json.dumps({"transcript": transcript.to_dict()}))
    segments = source_segments(tmp_path, "asset")
    plan = OutputPlan(
        "v",
        "c",
        "发布标题",
        (OutputItem("i", segments[0].segment_id, OutputRole.BODY),),
        social_copy="发布简介文案。",
    )
    repo = OutputCollectionRepository(tmp_path, "collection")
    repo.write(
        OutputCollection(
            "collection",
            "asset",
            (HighlightCandidate("c", "发布标题", "理由", (segments[0].segment_id,)),),
            (plan,),
        ),
        segments,
    )

    def execute(self: object, request: module.OutputRenderRequest) -> object:
        output = tmp_path / "exports/collection/v/export-id/v0001.mp4"
        output.parent.mkdir(parents=True)
        output.write_bytes(b"video")
        subtitle = output.with_suffix(".srt")
        subtitle.write_text("内容。")
        return SimpleNamespace(
            output_path=output,
            subtitle_path=subtitle,
            timeline=SimpleNamespace(estimated_duration_ms=2000),
        )

    def cover(video: Path, destination: Path, token: CancellationToken) -> None:
        assert video.name == "v0001.mp4"
        token.raise_if_cancelled()
        destination.write_bytes(b"jpeg")

    monkeypatch.setattr(module, "source_dimensions", lambda path: (1920, 1080))
    monkeypatch.setattr(module.RenderOutputUseCase, "execute", execute)
    monkeypatch.setattr(module, "_extract_cover", cover)
    result = export_output(
        tmp_path,
        "collection",
        "v",
        "export-id",
        1,
        "soft",
        0,
        "none",
        CancellationToken(),
    )
    assert result["title"] == "发布标题"
    assert result["social_copy"] == "发布简介文案。"
    assert result["cover_url"].endswith("v0001-cover.jpg")
