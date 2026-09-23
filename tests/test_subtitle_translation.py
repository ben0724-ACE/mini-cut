import asyncio
import json
from dataclasses import replace

import pytest

from minicut.errors import UserInputError
from minicut.llm_provider import TextModelRequest, TextModelResponse
from minicut.output_plan import (
    HighlightCandidate,
    OutputCollection,
    OutputItem,
    OutputPlan,
    OutputRole,
)
from minicut.output_timeline import (
    build_output_cues,
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
