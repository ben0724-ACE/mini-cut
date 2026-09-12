import unittest

from minicut.output_plan import OutputItem, OutputPlan, OutputRole
from minicut.output_timeline import (
    compile_output_timeline,
    inspect_output_context,
    map_output_words,
)
from minicut.semantic_segment import (
    ContextDirection,
    SegmentContextDependency,
    SemanticSegment,
)
from minicut.subtitle import build_word_cues, map_retained_words
from minicut.transcript import Word


class OutputHookTest(unittest.TestCase):
    def setUp(self) -> None:
        self.segments = (
            SemanticSegment("a", "背景。", 0, 800, ("ua",), ("wa",)),
            SemanticSegment(
                "c",
                "因此结论。",
                2000,
                2800,
                ("uc",),
                ("wc",),
                (SegmentContextDependency("a", ContextDirection.PRECEDING),),
            ),
        )
        self.plan = OutputPlan(
            "video",
            "candidate",
            "原话钩子",
            (
                OutputItem("hook-c", "c", OutputRole.HOOK),
                OutputItem("body-a", "a", OutputRole.BODY),
                OutputItem("body-c", "c", OutputRole.BODY),
            ),
        )
        self.words = (
            Word("wa", "背景。", 0, 800),
            Word("wc", "因此结论。", 2000, 2800),
        )

    def test_hook_and_body_reuse_source_with_separate_subtitle_instances(self) -> None:
        timeline = compile_output_timeline(self.plan, self.segments, "asset")
        with self.assertRaisesRegex(ValueError, "more than one Clip"):
            map_retained_words(timeline, self.segments, self.words)
        mapped = map_output_words(
            timeline, self.plan, self.segments, "asset", self.words
        )
        self.assertEqual(
            [(word.word_id, word.clip_id, word.start_ms) for word in mapped],
            [("wc", "hook-c", 0), ("wa", "body-a", 800), ("wc", "body-c", 1600)],
        )
        self.assertEqual(
            [cue.text for cue in build_word_cues(mapped, 2400)],
            ["因此结论。", "背景。", "因此结论。"],
        )
        warnings = inspect_output_context(self.plan, self.segments)
        self.assertEqual(
            [(issue.instance_id, issue.context_segment_id) for issue in warnings],
            [("hook-c", "a")],
        )

    def test_hook_order_body_presence_and_accidental_same_role_repetition(self) -> None:
        for items in (
            (self.plan.items[0],),
            (self.plan.items[1], self.plan.items[0]),
            (
                OutputItem("first", "c", OutputRole.BODY),
                OutputItem("second", "c", OutputRole.BODY),
            ),
        ):
            with self.subTest(items=items), self.assertRaises(ValueError):
                OutputPlan("video", "candidate", "title", items)

    def test_following_context_is_checked_without_fabrication(self) -> None:
        segment = SemanticSegment(
            "a",
            "例如。",
            0,
            800,
            ("ua",),
            ("wa",),
            (SegmentContextDependency("c", ContextDirection.FOLLOWING),),
        )
        source = (segment, SemanticSegment("c", "证据。", 2000, 2800, ("uc",), ("wc",)))
        plan = OutputPlan(
            "video",
            "candidate",
            "title",
            (
                OutputItem("a", "a", OutputRole.BODY),
                OutputItem("c", "c", OutputRole.BODY),
            ),
        )
        self.assertEqual(inspect_output_context(plan, source), ())
        reverse = OutputPlan("video", "candidate", "title", tuple(reversed(plan.items)))
        self.assertEqual(len(inspect_output_context(reverse, source)), 1)
