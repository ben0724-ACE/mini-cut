import asyncio
import json
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import pytest

from minicut.api import HighlightTaskBody
from minicut.errors import ProcessingError
from minicut.highlight_brief import HighlightPreset
from minicut.highlight_service import (
    edit_output_item,
    generate_highlights,
    rename_output,
)
from minicut.llm_provider import TextModelRequest, TextModelResponse
from minicut.media import MediaAsset, StreamInfo, StreamType
from minicut.output_render import OutputRenderRequest, RenderOutputUseCase
from minicut.output_repository import OutputCollectionRepository
from minicut.output_timeline import compile_output_timeline, map_output_words
from minicut.project import ProjectManifest, ProjectRepository
from minicut.sentence_boundaries import sentence_segments
from minicut.speech_cleanup import (
    Deletion,
    build_cleanup,
    cleanup_request,
    detect_silence,
    parse_cleanup_response,
    parse_silence,
    propose_deletions,
    silence_deletions,
)
from minicut.transcript import Transcript, TranscriptSource, Word
from minicut.transcription_task import CancellationToken


def transcript() -> Transcript:
    return Transcript(
        "t",
        TranscriptSource("a", "test", "test"),
        "zh",
        (
            Word("w0", "今天。", 100, 700),
            Word("w1", "呃", 800, 1000),
            Word("w2", "不可以。", 1200, 1900),
            Word("w3", "结束。", 4100, 4700),
        ),
    )


class Provider:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.requests: list[TextModelRequest] = []

    async def generate(self, request: TextModelRequest) -> TextModelResponse:
        self.requests.append(request)
        return TextModelResponse(json.dumps(self.payload), "test")


def test_deletion_only_protocol_and_invalid_word_ids() -> None:
    provider = Provider(
        {
            "deletions": [
                {"first_word_id": "w1", "last_word_id": "w1", "category": "填充词"}
            ]
        }
    )
    cuts, notes = asyncio.run(
        propose_deletions(transcript().words, provider, "test", "保留强调")
    )
    assert cuts == [Deletion(800, 1000, "填充词")]
    assert notes == []
    assert len(provider.requests) == 1
    assert '"title"' not in provider.requests[0].user_prompt
    provider.payload = {
        "deletions": [
            {"first_word_id": "invented", "last_word_id": "w1", "category": "填充词"}
        ]
    }
    cuts, notes = asyncio.run(
        propose_deletions(transcript().words, provider, "test", "")
    )
    assert cuts == [] and "未知词" in notes[0]


def test_long_input_covers_all_words_and_context_cannot_be_deleted() -> None:
    words = tuple(Word(f"w{i}", "内容", i * 100, i * 100 + 90) for i in range(1100))
    provider = Provider({"deletions": []})
    assert asyncio.run(propose_deletions(words, provider, "test", "")) == ([], [])
    owned = [
        w
        for request in provider.requests
        for w in json.loads(request.user_prompt)["owned_word_ids"]
    ]
    assert owned == [w.word_id for w in words]
    assert len(provider.requests) == 3


def test_silence_keeps_breathing_and_never_cuts_recognized_quiet_speech() -> None:
    assert parse_silence(
        "silence_start: 2.0\nsilence_end: 4.0\nsilence_start: 4.8", 5000
    ) == [(2000, 4000), (4800, 5000)]
    assert silence_deletions([(2000, 4000), (4700, 5000)], transcript().words) == [
        Deletion(2150, 3850, "长停顿")
    ]
    words = (Word("quiet", "不能删除", 0, 5000),)
    assert silence_deletions([(0, 5000)], words) == []
    assert silence_deletions([(0, 1000)], ()) == []


def test_partition_preserves_every_other_millisecond_and_subtitle_provenance() -> None:
    source = transcript()
    collection, notes = build_cleanup(
        source,
        5000,
        "原素材 · 清理版",
        "c",
        [Deletion(800, 1000, "填充词"), Deletion(2150, 3850, "长停顿")],
    )
    assert not notes
    plan = collection.plans[0]
    assert plan.social_copy is None and plan.workflow == "speech_cleanup"
    assert plan.items[0].source_start_ms == 0 and plan.items[-1].source_end_ms == 5000
    assert all(
        a.source_end_ms == b.source_start_ms
        for a, b in zip(plan.items, plan.items[1:], strict=False)
    )
    timeline = compile_output_timeline(plan, sentence_segments(source), "a")
    assert timeline.estimated_duration_ms == 3100
    mapped = map_output_words(
        timeline, plan, sentence_segments(source), "a", source.words
    )
    assert [w.word_id for w in mapped] == ["w0", "w2", "w3"]
    assert mapped[-1].start_ms == 2200
    restored = replace(plan, items=tuple(replace(i, deleted=False) for i in plan.items))
    assert (
        compile_output_timeline(
            restored, sentence_segments(source), "a"
        ).estimated_duration_ms
        == 5000
    )
    full, _ = build_cleanup(source, 5000, "full", "c", [])
    assert (
        compile_output_timeline(
            full.plans[0], sentence_segments(source), "a"
        ).estimated_duration_ms
        == 5000
    )
    guarded, notes = build_cleanup(
        source, 5000, "full", "c", [Deletion(0, 5000, "重复")]
    )
    assert notes and not any(i.deleted for i in guarded.plans[0].items)


def test_new_requests_normalize_cleanup_only_and_legacy_stays_legacy() -> None:
    brief = HighlightTaskBody(
        asset_id="a",
        preset=HighlightPreset.CLEAN_SPEECH,
        count=4,
        min_ms=1000,
        max_ms=2000,
        hook_ms=5000,
    ).brief()
    assert (
        brief.count,
        brief.hook_ms,
        brief.min_ms,
        brief.body_mode,
        brief.cleanup_version,
    ) == (1, None, None, "compact", 2)
    legacy = HighlightTaskBody(
        asset_id="a", preset=HighlightPreset.CLEAN_SPEECH, count=2, cleanup_version=None
    ).brief()
    assert legacy.count == 2 and "cleanup_version" not in legacy.to_dict()


@pytest.mark.parametrize("version", [1, 2])
def test_real_media_cleanup_render_restore_and_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, version: int
) -> None:
    source = tmp_path / "口播.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=160x120:r=25:d=5",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=5",
            "-af",
            "volume=enable='between(t,2,4)':volume=0",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-shortest",
            str(source),
        ],
        check=True,
        capture_output=True,
    )
    asset = MediaAsset(
        "a",
        str(source),
        5000,
        (
            StreamInfo(0, StreamType.VIDEO, "h264"),
            StreamInfo(1, StreamType.AUDIO, "aac"),
        ),
        "fixture",
    )
    ProjectRepository(tmp_path).create(ProjectManifest("project", (asset,)))
    tx = transcript()
    cache = tmp_path / ".minicut/transcripts/a.json"
    cache.parent.mkdir(parents=True)
    cache.write_text(json.dumps({"transcript": tx.to_dict()}))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-no-network")
    assert len(detect_silence(source, 5000, CancellationToken())) == 1
    provider = Provider(
        {
            "deletions": [
                {
                    "first_word_id": "w1" if version == 1 else "1",
                    "last_word_id": "w1" if version == 1 else "1",
                    "category": "填充词",
                }
            ]
        }
    )
    brief = HighlightTaskBody(
        asset_id="a",
        preset=HighlightPreset.CLEAN_SPEECH,
        count=1,
        editing_prompt="清理",
        cleanup_version=version,
    ).brief()
    with (
        patch("minicut.speech_cleanup.DeepSeekProvider", return_value=provider),
        patch(
            "minicut.highlight_service.plan_highlights",
            side_effect=AssertionError("must not select highlights"),
        ),
        patch(
            "minicut.highlight_service.refine_boundaries",
            side_effect=AssertionError("must not refine highlights"),
        ),
    ):
        result = generate_highlights(tmp_path, "a", "c", brief)
    assert len(provider.requests) == 1
    assert (
        json.loads(provider.requests[0].user_prompt)["version"]
        == f"speech-cleanup-v{version}"
    )
    rows = cast(list[dict[str, Any]], result["outputs"])
    assert rows[0]["title"] == "口播 · 清理版"
    segments = sentence_segments(tx)
    repo = OutputCollectionRepository(tmp_path, "c")
    plan = repo.read(segments).plans[0]
    assert len([i for i in plan.items if i.deleted]) == 2
    rendered = RenderOutputUseCase().execute(
        OutputRenderRequest(tmp_path, "c", "cleanup", segments, tx)
    )
    media = json.loads(
        subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(rendered.output_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    assert {s["codec_type"] for s in media["streams"]} >= {"video", "audio", "subtitle"}
    assert (
        abs(
            float(media["format"]["duration"]) * 1000
            - rendered.timeline.estimated_duration_ms
        )
        < 150
    )
    subtitle = rendered.subtitle_path.read_text()
    assert "呃" not in subtitle and "不可以" in subtitle and "结束" in subtitle
    audio = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "info",
            "-i",
            str(rendered.output_path),
            "-af",
            "volumedetect",
            "-f",
            "null",
            "-",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stderr
    assert "mean_volume: -inf" not in audio and "mean_volume:" in audio
    removed = next(i for i in plan.items if i.cleanup_category == "填充词")
    restored = edit_output_item(
        tmp_path, "c", "cleanup", removed.instance_id, deleted=False
    )
    assert (
        cast(list[dict[str, Any]], restored["outputs"])[0]["duration_ms"]
        == rows[0]["duration_ms"] + 200
    )
    renamed = rename_output(tmp_path, "c", "cleanup", 2, "人工作品名")
    assert cast(list[dict[str, Any]], renamed["outputs"])[0]["title"] == "人工作品名"
    assert repo.version_path("cleanup", 1).exists()
    assert len(provider.requests) == 1


@pytest.mark.parametrize("saved_version", [None, 1])
def test_api_recovery_preserves_legacy_cleanup_and_new_snapshot(
    tmp_path: Path, saved_version: int | None
) -> None:
    import httpx

    from minicut.api import create_app
    from minicut.highlight_brief import HighlightBrief

    root = tmp_path / "demo"
    ProjectRepository(root).create(
        ProjectManifest("demo", (MediaAsset("a", "/a.mp4", 5000, (), "fixture"),))
    )
    cache = root / ".minicut/transcripts/a.json"
    cache.parent.mkdir(parents=True)
    cache.write_text("{}")
    jobs = root / ".minicut/jobs"
    jobs.mkdir()
    old_request = {"asset_id": "a", "preset": "clean_speech", "count": 2}
    if saved_version is not None:
        old_request["cleanup_version"] = saved_version
    (jobs / "old.json").write_text(
        json.dumps(
            {
                "task_id": "old",
                "kind": "highlights",
                "status": "failed",
                "resumable": True,
                "request": old_request,
                "result": None,
                "error": "interrupted",
            }
        )
    )
    seen: list[HighlightBrief] = []

    def generate(
        project: Path, asset: str, collection: str, brief: HighlightBrief
    ) -> dict[str, object]:
        seen.append(brief)
        return {"collection_id": collection, "asset_id": asset, "outputs": []}

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(
                app=create_app(tmp_path, highlights=generate)
            ),
            base_url="http://test",
        ) as client:
            response = await client.post("/api/projects/demo/tasks/old/resume")
            assert response.status_code == 202
            assert seen[-1].cleanup_version == saved_version
            assert seen[-1].count == (2 if saved_version is None else 1)
            response = await client.post(
                "/api/projects/demo/tasks/highlights",
                json={k: v for k, v in old_request.items() if k != "cleanup_version"},
                headers={"Idempotency-Key": "new"},
            )
            assert response.status_code == 202
            assert seen[-1].cleanup_version == 2 and seen[-1].count == 1
            saved = json.loads((jobs / "new.json").read_text())
            assert saved["generation_config"]["cleanup_version"] == 2
            saved.update(status="failed", result=None, error="interrupted")
            (jobs / "new.json").write_text(json.dumps(saved))
            response = await client.post("/api/projects/demo/tasks/new/resume")
            assert response.status_code == 202
            assert seen[-1].cleanup_version == 2

    asyncio.run(run())


@pytest.mark.parametrize(
    "invalid",
    [
        {"first_word_id": "w3", "last_word_id": "w2", "category": "重复"},
        {"first_word_id": "unknown", "last_word_id": "w3", "category": "重复"},
        {"first_word_id": "w2", "last_word_id": "w3", "category": "unsupported"},
        {"first_word_id": None, "last_word_id": [], "category": "重复"},
        {"first_word_id": "w3"},
        None,
    ],
)
def test_invalid_suggestion_preserves_source_without_aborting_valid_rows(
    invalid: object,
) -> None:
    source = transcript()
    content = json.dumps(
        {
            "deletions": [
                invalid,
                {"first_word_id": "w1", "last_word_id": "w1", "category": "填充词"},
            ]
        }
    )
    cuts, notes = parse_cleanup_response(content, source.words, source.words, 1)
    assert cuts == [Deletion(800, 1000, "填充词")]
    assert notes and "保留" in notes[0]
    collection, _ = build_cleanup(source, 5000, "清理", "c", cuts)
    assert (
        compile_output_timeline(
            collection.plans[0], sentence_segments(source), "a"
        ).estimated_duration_ms
        == 4800
    )


def test_reversed_range_is_not_repaired_or_removed_by_overlapping_proposal() -> None:
    source = transcript()
    cuts, notes = parse_cleanup_response(
        json.dumps(
            {
                "deletions": [
                    {"first_word_id": "w1", "last_word_id": "w0", "category": "重复"},
                    {"first_word_id": "w0", "last_word_id": "w1", "category": "重复"},
                ]
            }
        ),
        source.words,
        source.words,
        1,
    )
    assert cuts == []
    assert "顺序颠倒" in notes[0] and "重叠" in notes[1]


@pytest.mark.parametrize(
    "content", ["not json", '{"deletions":null}', '{"deletions":{}}', "[]"]
)
def test_invalid_response_container_still_fails_explicitly(content: str) -> None:
    with pytest.raises(ProcessingError, match="第 2 段响应不是有效的删除列表"):
        parse_cleanup_response(content, transcript().words, transcript().words, 2)


@pytest.mark.parametrize("version", [1, 2])
def test_chunk_aliases_keep_global_provenance_and_reject_context_deletions(
    version: int,
) -> None:
    words = tuple(
        Word(f"word:{i:064x}", "内容", i * 100, i * 100 + 90) for i in range(1100)
    )
    covered: list[str] = []
    for offset in (0, 500, 1000):
        request, aliases = cleanup_request(words, offset, "test", "保留强调", version)
        data = json.loads(request.user_prompt)
        if aliases is None:
            covered.extend(data["owned_word_ids"])
            owned_id, context_id = (
                words[offset].word_id,
                words[0 if offset == 0 else offset - 60].word_id,
            )
        else:
            first, last = map(int, data["owned_range"])
            covered.extend(aliases[str(i)] for i in range(first, last + 1))
            assert "word:" not in request.user_prompt and "owned_word_ids" not in data
            owned_id, context_id = str(first), "0"
        cuts, notes = parse_cleanup_response(
            json.dumps(
                {
                    "deletions": [
                        {
                            "first_word_id": owned_id,
                            "last_word_id": owned_id,
                            "category": "填充词",
                        }
                    ]
                }
            ),
            words[offset : offset + 500],
            words[max(0, offset - 60) : offset + 560],
            1,
            aliases=aliases,
        )
        assert (
            cuts == [Deletion(offset * 100, offset * 100 + 90, "填充词")] and not notes
        )
        if offset:
            cuts, notes = parse_cleanup_response(
                json.dumps(
                    {
                        "deletions": [
                            {
                                "first_word_id": context_id,
                                "last_word_id": owned_id,
                                "category": "重复",
                            }
                        ]
                    }
                ),
                words[offset : offset + 500],
                words[offset - 60 : offset + 560],
                2,
                aliases=aliases,
            )
            assert cuts == [] and "上下文词" in notes[0]
    assert covered == [w.word_id for w in words]


@pytest.mark.parametrize(
    "bad",
    [
        {"first_word_id": "1", "last_word_id": "0", "category": "重复"},
        {"first_word_id": "0", "last_word_id": "1", "category": "不支持"},
        {"first_word_id": "1", "last_word_id": None, "category": "重复"},
        {"first_word_id": "1", "last_word_id": "1"},
        {"first_word_id": "w1", "last_word_id": "1", "category": "重复"},
    ],
)
def test_alias_validation_preserves_ambiguous_original_ranges(bad: object) -> None:
    source = transcript()
    _, aliases = cleanup_request(source.words, 0, "test", "", 2)
    cuts, notes = parse_cleanup_response(
        json.dumps(
            {
                "deletions": [
                    bad,
                    {"first_word_id": "1", "last_word_id": "1", "category": "填充词"},
                    {"first_word_id": "3", "last_word_id": "3", "category": "重复"},
                ]
            }
        ),
        source.words,
        source.words,
        1,
        aliases=aliases,
    )
    assert cuts == [Deletion(4100, 4700, "重复")]
    assert notes and "保留" in notes[0]
