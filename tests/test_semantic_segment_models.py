import json
import unittest
from collections.abc import Callable

from minicut.semantic_segment import (
    ContextDirection,
    SegmentContextDependency,
    SemanticSegment,
    generate_segment_id,
    validate_segment_context_dependencies,
)


def _segment(
    segment_id: str,
    start_ms: int,
    end_ms: int,
    *,
    dependencies: tuple[SegmentContextDependency, ...] = (),
) -> SemanticSegment:
    ordinal = int(segment_id.rsplit("-", 1)[-1])
    return SemanticSegment(
        segment_id=segment_id,
        text=f"segment {ordinal}",
        start_ms=start_ms,
        end_ms=end_ms,
        utterance_ids=(f"utterance-{ordinal}",),
        word_ids=(f"word-{ordinal}",),
        context_dependencies=dependencies,
    )


class SemanticSegmentModelTest(unittest.TestCase):
    def test_segment_and_dependencies_round_trip_through_json(self) -> None:
        segment = SemanticSegment(
            segment_id="segment-2",
            text="所以需要保留上文",
            start_ms=1_000,
            end_ms=2_000,
            utterance_ids=("utterance-2",),
            word_ids=("word-2", "word-3"),
            context_dependencies=(
                SegmentContextDependency("segment-1", ContextDirection.PRECEDING),
                SegmentContextDependency("segment-3", ContextDirection.FOLLOWING),
            ),
        )

        restored = SemanticSegment.from_dict(
            json.loads(json.dumps(segment.to_dict(), ensure_ascii=False))
        )

        self.assertEqual(restored, segment)

    def test_segment_rejects_invalid_identity_content_and_coverage(self) -> None:
        invalid_factories: tuple[Callable[[], SemanticSegment], ...] = (
            lambda: SemanticSegment("", "正文", 0, 100, ("utterance-1",), ("word-1",)),
            lambda: SemanticSegment(
                "segment-1", "  ", 0, 100, ("utterance-1",), ("word-1",)
            ),
            lambda: SemanticSegment(
                "segment-1", "正文", -1, 100, ("utterance-1",), ("word-1",)
            ),
            lambda: SemanticSegment(
                "segment-1", "正文", 0, 0, ("utterance-1",), ("word-1",)
            ),
            lambda: SemanticSegment("segment-1", "正文", 0, 100, (), ("word-1",)),
            lambda: SemanticSegment("segment-1", "正文", 0, 100, ("utterance-1",), ()),
            lambda: SemanticSegment(
                "segment-1",
                "正文",
                0,
                100,
                ("utterance-1",),
                ("word-1", "word-1"),
            ),
        )

        for index, create_segment in enumerate(invalid_factories):
            with self.subTest(index=index):
                with self.assertRaises(ValueError):
                    create_segment()

    def test_segment_rejects_self_and_duplicate_dependencies(self) -> None:
        with self.assertRaisesRegex(ValueError, "dependency"):
            SemanticSegment(
                "segment-1",
                "正文",
                0,
                100,
                ("utterance-1",),
                ("word-1",),
                (
                    SegmentContextDependency(
                        "segment-1",
                        ContextDirection.PRECEDING,
                    ),
                ),
            )

        duplicate = SegmentContextDependency(
            "segment-2",
            ContextDirection.FOLLOWING,
        )
        with self.assertRaisesRegex(ValueError, "dependency"):
            SemanticSegment(
                "segment-1",
                "正文",
                0,
                100,
                ("utterance-1",),
                ("word-1",),
                (duplicate, duplicate),
            )


class SegmentContextValidationTest(unittest.TestCase):
    def test_known_dependencies_in_the_declared_direction_are_valid(self) -> None:
        segments = (
            _segment("segment-1", 0, 500),
            _segment(
                "segment-2",
                600,
                1_000,
                dependencies=(
                    SegmentContextDependency(
                        "segment-1",
                        ContextDirection.PRECEDING,
                    ),
                    SegmentContextDependency(
                        "segment-3",
                        ContextDirection.FOLLOWING,
                    ),
                ),
            ),
            _segment("segment-3", 1_100, 1_500),
        )

        validate_segment_context_dependencies(segments)

    def test_unknown_dependency_is_rejected(self) -> None:
        segments = (
            _segment(
                "segment-1",
                0,
                500,
                dependencies=(
                    SegmentContextDependency(
                        "missing",
                        ContextDirection.FOLLOWING,
                    ),
                ),
            ),
        )

        with self.assertRaisesRegex(ValueError, "unknown"):
            validate_segment_context_dependencies(segments)

    def test_dependency_direction_must_match_source_time_order(self) -> None:
        segments = (
            _segment("segment-1", 0, 500),
            _segment(
                "segment-2",
                600,
                1_000,
                dependencies=(
                    SegmentContextDependency(
                        "segment-1",
                        ContextDirection.FOLLOWING,
                    ),
                ),
            ),
        )

        with self.assertRaisesRegex(ValueError, "direction"):
            validate_segment_context_dependencies(segments)


class SegmentIdTest(unittest.TestCase):
    def test_id_is_stable_without_adding_a_content_hash(self) -> None:
        first = generate_segment_id("transcript-1", 3)

        self.assertEqual(first, "segment:transcript-1:3")
        self.assertEqual(generate_segment_id("transcript-1", 3), first)
        self.assertNotEqual(generate_segment_id("transcript-1", 4), first)
        self.assertNotEqual(generate_segment_id("transcript-2", 3), first)

    def test_id_rejects_blank_transcript_and_negative_ordinal(self) -> None:
        with self.assertRaisesRegex(ValueError, "transcript"):
            generate_segment_id(" ", 0)
        with self.assertRaisesRegex(ValueError, "ordinal"):
            generate_segment_id("transcript-1", -1)


if __name__ == "__main__":
    unittest.main()
