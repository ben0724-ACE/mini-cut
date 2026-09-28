import asyncio
import json
from dataclasses import replace
from pathlib import Path
from threading import Lock

import pytest

from minicut.errors import UserInputError
from minicut.highlight_service import translate_output_subtitles
from minicut.llm_provider import TextModelRequest, TextModelResponse
from minicut.output_plan import (
    HighlightCandidate,
    OutputCollection,
    OutputItem,
    OutputPlan,
    OutputRole,
)
from minicut.output_repository import OutputCollectionRepository
from minicut.output_timeline import (
    build_output_cues,
    build_output_pages,
    compile_output_timeline,
    map_output_words,
)
from minicut.semantic_segment import SemanticSegment
from minicut.subtitle_translation import translate_collection
from minicut.transcript import Transcript, TranscriptSource, Word


class Translator:
    def __init__(self, bad: bool = False) -> None:
        self.requests: list[TextModelRequest] = []
        self.bad = bad

    async def generate(self, request: TextModelRequest) -> TextModelResponse:
        self.requests.append(request)
        payload = json.loads(request.user_prompt)
        rows = [{"id": row["id"], "text": "你好"} for row in payload["subtitles"]]
        return TextModelResponse(
            json.dumps({"translations": [] if self.bad else rows}), "test"
        )


def fixture() -> tuple[OutputCollection, tuple[SemanticSegment, ...], Transcript]:
    segment = SemanticSegment("s", "Hello", 0, 2000, ("u",), ("w",))
    t = Transcript(
        "t", TranscriptSource("a", "test", "test"), "en", (Word("w", "Hello", 0, 2000),)
    )
    items = (
        OutputItem("hook", "s", OutputRole.HOOK),
        OutputItem("body", "s", OutputRole.BODY),
    )
    c = OutputCollection(
        "c",
        "a",
        (HighlightCandidate("candidate", "title", "reason", ("s",)),),
        (
            OutputPlan(
                "v", "candidate", "title", items, hook_transition_kind="tv_static"
            ),
        ),
    )
    return c, (segment,), t


@pytest.mark.parametrize("mode", ["bilingual", "translated"])
def test_translation_deduplicates_and_exports_selected_language_without_timing_changes(
    mode: str,
) -> None:
    c, s, t = fixture()
    provider = Translator()
    translated = asyncio.run(
        translate_collection(c, s, t, provider, "test", "zh", mode)
    )
    assert len(provider.requests) == 1
    assert len(json.loads(provider.requests[0].user_prompt)["subtitles"]) == 1
    plan = translated.plans[0]
    assert plan.subtitle_mode == mode
    assert OutputPlan.from_dict(plan.to_dict()) == plan
    timeline = compile_output_timeline(plan, s, "a")
    assert timeline == compile_output_timeline(c.plans[0], s, "a")
    mapped = map_output_words(timeline, plan, s, "a", t.words)
    cues = build_output_cues(timeline, plan, mapped)
    assert len(cues) == 2
    assert all("你好" in cue.text for cue in cues)
    assert all(("Hello" in cue.text) == (mode == "bilingual") for cue in cues)
    assert cues[1].start_ms == 2300
    edited = replace(
        plan, items=(replace(plan.items[0], translation_text="您好"), plan.items[1])
    )
    assert "您好" in build_output_cues(timeline, edited, mapped)[0].text
    assert c.plans[0].items[0].translation_text is None


def test_incomplete_translation_fails_without_mutating_candidate() -> None:
    c, s, t = fixture()
    with pytest.raises(UserInputError, match="未写入部分译文"):
        asyncio.run(
            translate_collection(c, s, t, Translator(True), "test", "en", "translated")
        )
    assert c.plans[0].items[0].translation_text is None


def test_later_translation_preserves_existing_manual_translation() -> None:
    c, s, t = fixture()
    plan = c.plans[0]
    c = replace(
        c,
        plans=(
            replace(
                plan,
                items=(
                    replace(
                        plan.items[0],
                        translation_text="您好",
                        translation_language="zh",
                    ),
                    plan.items[1],
                ),
            ),
        ),
    )
    provider = Translator()
    translated = asyncio.run(
        translate_collection(
            c,
            s,
            t,
            provider,
            "test",
            "zh",
            "bilingual",
            only_missing=True,
        )
    )
    assert translated.plans[0].items[0].translation_text == "您好"
    assert translated.plans[0].items[1].translation_text == "你好"
    assert len(provider.requests) == 1


def test_post_generation_translation_saves_one_version_without_paid_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c, segments, transcript = fixture()
    plan = c.plans[0]
    c = replace(
        c,
        plans=(
            replace(
                plan,
                items=(
                    replace(
                        plan.items[0],
                        translation_text="您好",
                        translation_language="zh",
                    ),
                    plan.items[1],
                ),
            ),
        ),
    )
    repository = OutputCollectionRepository(tmp_path, "c")
    repository.write_segments(segments)
    repository.write(c, segments)
    repository.write_highlight_result(
        {
            "asset_id": "a",
            "collection_id": "c",
            "source_duration_ms": 2000,
            "outputs": [{"output_id": "v", "title": "title", "reason": "reason"}],
        }
    )
    path = tmp_path / ".minicut/transcripts/a.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"transcript": transcript.to_dict()}))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only")
    monkeypatch.setattr(
        "minicut.highlight_service.DeepSeekProvider",
        lambda *args, **kwargs: Translator(),
    )
    result = translate_output_subtitles(tmp_path, "c", "v", 1, "zh", Lock())
    assert result["outputs"][0]["revision"] == 2
    saved = repository.read(segments).plans[0]
    assert [item.translation_text for item in saved.items] == ["您好", "你好"]
    with pytest.raises(UserInputError, match="新版本"):
        translate_output_subtitles(tmp_path, "c", "v", 1, "zh", Lock())


def test_bilingual_sentence_stays_together_when_languages_wrap_differently() -> None:
    segment = SemanticSegment(
        "s",
        "Well, it's pretty obvious at this point that AI can be very dangerous.",
        0,
        8040,
        ("u",),
        ("w",),
    )
    plan = OutputPlan(
        "v",
        "c",
        "T",
        (
            OutputItem(
                "body",
                "s",
                OutputRole.BODY,
                display_text=segment.text,
                translation_text="嗯，现在已经很明显了，AI 可能会非常危险。",
                translation_language="zh",
            ),
        ),
    )
    timeline = compile_output_timeline(plan, (segment,), "a")
    pages = build_output_pages(timeline, plan, ())
    cues = build_output_cues(timeline, plan, ())
    assert len(cues) == 2
    assert [(cue.start_ms, cue.end_ms) for cue in cues] == [
        (0, 4020),
        (4020, 8040),
    ]
    assert all(page.source and page.translation for page in pages)
    assert all(len(cue.text.splitlines()) <= 2 for cue in cues)
    assert " ".join(page.source.replace("\n", " ") for page in pages) == segment.text
    assert "".join(page.translation or "" for page in pages) == (
        "嗯，现在已经很明显了，AI 可能会非常危险。"
    )
