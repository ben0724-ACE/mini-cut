import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest

from minicut.highlight_service import (
    RevisionConflict,
    edit_output_item,
    rename_output,
    translate_output_subtitles,
)
from minicut.media import MediaAsset
from minicut.output_plan import (
    HighlightCandidate,
    OutputCollection,
    OutputItem,
    OutputPlan,
    OutputRole,
)
from minicut.output_repository import OutputCollectionRepository
from minicut.project import ProjectManifest, ProjectRepository
from minicut.semantic_segment import SemanticSegment
from minicut.transcript import Transcript, TranscriptSource, Word


@pytest.fixture
def repository(tmp_path: Path) -> OutputCollectionRepository:
    ProjectRepository(tmp_path).create(
        ProjectManifest("demo", (MediaAsset("asset", "/source.mp4", 2000, (), "test"),))
    )
    transcript = Transcript(
        "t",
        TranscriptSource("asset", "test", "tiny"),
        "en",
        (Word("w1", "One.", 0, 1000), Word("w2", "Two.", 1000, 2000)),
    )
    path = tmp_path / ".minicut/transcripts/asset.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"transcript": transcript.to_dict()}))
    segments = (
        SemanticSegment("s1", "One.", 0, 1000, ("u1",), ("w1",)),
        SemanticSegment("s2", "Two.", 1000, 2000, ("u2",), ("w2",)),
    )
    items = tuple(OutputItem(f"i{n}", f"s{n}", OutputRole.BODY) for n in (1, 2))
    repository = OutputCollectionRepository(tmp_path, "c")
    repository.write_segments(segments)
    repository.write(
        OutputCollection(
            "c",
            "asset",
            (HighlightCandidate("candidate", "Title", "Reason", ("s1", "s2")),),
            tuple(
                OutputPlan(output, "candidate", "Title", items)
                for output in ("v", "other")
            ),
        ),
        segments,
    )
    repository.write_highlight_result(
        {
            "asset_id": "asset",
            "collection_id": "c",
            "source_duration_ms": 2000,
            "outputs": [{"output_id": output} for output in ("v", "other")],
        }
    )
    return repository


@pytest.mark.parametrize("second_output", ["v", "other"])
def test_direct_concurrent_edits_preserve_both_changes_and_history(
    repository: OutputCollectionRepository,
    monkeypatch: pytest.MonkeyPatch,
    second_output: str,
) -> None:
    writing, release, second_started, second_finished = (Event() for _ in range(4))
    original_write = OutputCollectionRepository.write
    paused = False

    def pause_write(
        repo: OutputCollectionRepository,
        collection: OutputCollection,
        segments: tuple[SemanticSegment, ...],
    ) -> None:
        nonlocal paused
        if not paused:
            paused = True
            writing.set()
            assert release.wait(5)
        original_write(repo, collection, segments)

    monkeypatch.setattr(OutputCollectionRepository, "write", pause_write)
    project = repository.project_directory

    def edit_second() -> dict[str, object]:
        second_started.set()
        try:
            return edit_output_item(
                project=project / ".." / project.name,
                collection_id="c",
                output_id=second_output,
                instance_id="i2",
                display_text="Second correction",
            )
        finally:
            second_finished.set()

    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(
            edit_output_item, project, "c", "v", "i1", display_text="First correction"
        )
        try:
            assert writing.wait(5)
            second = workers.submit(edit_second)
            assert second_started.wait(5)
            assert not second_finished.wait(0.2)
        finally:
            release.set()
        first.result(timeout=5)
        second.result(timeout=5)

    saved = json.loads(repository.path.read_text())
    plans = {plan["output_id"]: plan for plan in saved["plans"]}
    assert plans["v"]["items"][0]["display_text"] == "First correction"
    assert plans[second_output]["items"][1]["display_text"] == "Second correction"
    assert plans["v"]["revision"] == (3 if second_output == "v" else 2)
    original = json.loads(repository.version_path("v", 1).read_text())
    assert original["items"][0]["display_text"] is None
    if second_output == "v":
        prior = json.loads(repository.version_path("v", 2).read_text())
        assert prior["items"][0]["display_text"] == "First correction"
        assert prior["items"][1]["display_text"] is None


@pytest.mark.parametrize("changed_output", ["v", "other"])
def test_translation_rechecks_revision_without_blocking_edits(
    repository: OutputCollectionRepository,
    monkeypatch: pytest.MonkeyPatch,
    changed_output: str,
) -> None:
    translating, release = Event(), Event()

    async def translate(
        collection: OutputCollection,
        *args: object,
        **kwargs: object,
    ) -> OutputCollection:
        translating.set()
        assert release.wait(5)
        plan = collection.plans[0]
        return replace(
            collection,
            plans=(
                replace(
                    plan,
                    items=tuple(
                        replace(
                            item, translation_text="译文", translation_language="zh"
                        )
                        for item in plan.items
                    ),
                ),
            ),
        )

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-no-network")
    monkeypatch.setattr("minicut.subtitle_translation.translate_collection", translate)
    project = repository.project_directory
    with ThreadPoolExecutor(max_workers=2) as workers:
        translation = workers.submit(
            translate_output_subtitles, project, "c", "v", 1, "zh"
        )
        try:
            assert translating.wait(5)
            edit = workers.submit(
                rename_output, project, "c", changed_output, 1, "Changed title"
            )
            edit.result(timeout=2)
        finally:
            release.set()
        if changed_output == "v":
            with pytest.raises(RevisionConflict, match="翻译期间作品已修改"):
                translation.result(timeout=5)
        else:
            translation.result(timeout=5)
    saved = json.loads(repository.path.read_text())
    plans = {plan["output_id"]: plan for plan in saved["plans"]}
    assert plans[changed_output]["title"] == "Changed title"
    assert plans["v"]["revision"] == 2
    assert plans["v"]["items"][0]["translation_text"] == (
        None if changed_output == "v" else "译文"
    )
