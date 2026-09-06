import tempfile
import unittest
from pathlib import Path

from minicut.segmentation_debug import (
    export_segmentation_debug,
    render_segmentation_debug_html,
)
from minicut.semantic_segment import (
    ContextDirection,
    SegmentContextDependency,
    SegmentLabel,
    SemanticSegment,
)


def _segments() -> tuple[SemanticSegment, ...]:
    return (
        SemanticSegment(
            segment_id="segment-1",
            text="<script>alert('unsafe')</script>",
            start_ms=1_000,
            end_ms=2_500,
            utterance_ids=("utterance-1",),
            word_ids=("word-1", "word-2"),
            labels=(SegmentLabel.CONTENT,),
        ),
        SemanticSegment(
            segment_id="segment-2",
            text="嗯。",
            start_ms=3_000,
            end_ms=4_000,
            utterance_ids=("utterance-2",),
            word_ids=("word-3",),
            context_dependencies=(
                SegmentContextDependency(
                    "segment-1",
                    ContextDirection.PRECEDING,
                ),
            ),
            labels=(SegmentLabel.FILLER,),
        ),
    )


class SegmentationDebugHtmlTest(unittest.TestCase):
    def test_html_visualizes_timing_labels_coverage_and_dependencies(self) -> None:
        result = render_segmentation_debug_html(_segments())

        self.assertIn("MiniCut Segmentation Debug", result)
        self.assertIn('data-segment-id="segment-1"', result)
        self.assertIn('left:25.000%;width:37.500%"', result)
        self.assertIn("00:00:01.000", result)
        self.assertIn("00:00:02.500", result)
        self.assertIn("content", result)
        self.assertIn("filler", result)
        self.assertIn("word-1, word-2", result)
        self.assertIn("preceding → segment-1", result)

    def test_segment_text_and_attributes_are_html_escaped(self) -> None:
        result = render_segmentation_debug_html(_segments())

        self.assertNotIn("<script>alert", result)
        self.assertIn("&lt;script&gt;alert(&#x27;unsafe&#x27;)&lt;/script&gt;", result)

    def test_empty_export_is_readable_and_rendering_is_deterministic(self) -> None:
        first = render_segmentation_debug_html(())
        second = render_segmentation_debug_html(())

        self.assertEqual(second, first)
        self.assertIn("No semantic segments.", first)

    def test_export_writes_utf8_html_and_creates_parent_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "debug" / "segments.html"

            result = export_segmentation_debug(_segments(), destination)

            self.assertEqual(result, destination)
            self.assertEqual(
                destination.read_text(encoding="utf-8"),
                render_segmentation_debug_html(_segments()),
            )


if __name__ == "__main__":
    unittest.main()
