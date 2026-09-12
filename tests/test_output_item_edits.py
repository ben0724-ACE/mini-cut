from dataclasses import replace

from minicut.output_plan import OutputItem, OutputPlan, OutputRole
from minicut.output_timeline import build_output_cues, compile_output_timeline
from minicut.semantic_segment import SemanticSegment
from minicut.subtitle import MappedWord


def test_deleted_instance_is_skipped_but_source_reference_survives() -> None:
    source = (
        SemanticSegment("a", "第一句", 0, 1000, ("u1",), ("w1",)),
        SemanticSegment("b", "第二句", 2000, 3000, ("u2",), ("w2",)),
    )
    first = OutputItem("first", "a", OutputRole.BODY)
    second = OutputItem("second", "b", OutputRole.BODY)
    plan = OutputPlan(
        "video",
        "candidate",
        "测试",
        (replace(first, deleted=True, display_text="更正文字"), second),
    )
    timeline = compile_output_timeline(plan, source, "asset")
    assert [clip.clip_id for clip in timeline.clips] == ["second"]
    assert plan.items[0].segment_id == "a"
    restored = replace(plan, items=(replace(plan.items[0], deleted=False), second))
    assert (
        compile_output_timeline(restored, source, "asset").estimated_duration_ms == 2000
    )


def test_display_override_respects_cut_and_word_ids_are_unchanged() -> None:
    source = (
        SemanticSegment("a", "原文", 0, 1000, ("u1",), ("w1",)),
        SemanticSegment("b", "第二句", 2000, 3000, ("u2",), ("w2",)),
    )
    plan = OutputPlan(
        "video",
        "candidate",
        "测试",
        (
            OutputItem("i1", "a", OutputRole.BODY, display_text="中文术语"),
            OutputItem("i2", "b", OutputRole.BODY),
        ),
    )
    timeline = compile_output_timeline(plan, source, "asset")
    mapped = (
        MappedWord("w1", "原文", 0, 1000, "i1"),
        MappedWord("w2", "第二句", 1000, 2000, "i2"),
    )
    cues = build_output_cues(timeline, plan, mapped)
    assert [(cue.start_ms, cue.end_ms, cue.text) for cue in cues] == [
        (0, 1000, "中文术语"),
        (1000, 2000, "第二句"),
    ]
    assert [word.word_id for word in mapped] == ["w1", "w2"]
