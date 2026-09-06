"""Human-readable HTML export for semantic segmentation debugging."""

from html import escape
from pathlib import Path

from minicut.semantic_segment import SemanticSegment


def _format_time(milliseconds: int) -> str:
    seconds, remainder_ms = divmod(milliseconds, 1_000)
    minutes, remainder_seconds = divmod(seconds, 60)
    hours, remainder_minutes = divmod(minutes, 60)
    return (
        f"{hours:02d}:{remainder_minutes:02d}:"
        f"{remainder_seconds:02d}.{remainder_ms:03d}"
    )


def _format_dependencies(segment: SemanticSegment) -> str:
    if not segment.context_dependencies:
        return "—"
    return ", ".join(
        f"{escape(dependency.direction.value)} → {escape(dependency.segment_id)}"
        for dependency in segment.context_dependencies
    )


def _format_labels(segment: SemanticSegment) -> str:
    if not segment.labels:
        return "unlabeled"
    return ", ".join(escape(label.value) for label in segment.labels)


def _timeline_bars(segments: tuple[SemanticSegment, ...]) -> str:
    if not segments:
        return '<p class="empty">No semantic segments.</p>'

    timeline_end_ms = max(segment.end_ms for segment in segments)
    bars: list[str] = []
    for segment in segments:
        left = segment.start_ms / timeline_end_ms * 100
        width = (segment.end_ms - segment.start_ms) / timeline_end_ms * 100
        segment_id = escape(segment.segment_id, quote=True)
        label = escape(segment.segment_id)
        bars.append(
            f'<div class="segment-bar" data-segment-id="{segment_id}" '
            f'style="left:{left:.3f}%;width:{width:.3f}%" '
            f'title="{segment_id}">{label}</div>'
        )
    return (
        '<div class="timeline" aria-label="Semantic segment timeline">'
        + "".join(bars)
        + "</div>"
    )


def _segment_rows(segments: tuple[SemanticSegment, ...]) -> str:
    rows: list[str] = []
    for segment in segments:
        segment_id = escape(segment.segment_id, quote=True)
        word_ids = ", ".join(escape(word_id) for word_id in segment.word_ids)
        utterance_ids = ", ".join(
            escape(utterance_id) for utterance_id in segment.utterance_ids
        )
        rows.append(
            f'<tr data-segment-id="{segment_id}">'
            f"<td><code>{escape(segment.segment_id)}</code></td>"
            f"<td>{_format_time(segment.start_ms)} – {_format_time(segment.end_ms)}</td>"
            f"<td>{escape(segment.text)}</td>"
            f"<td>{_format_labels(segment)}</td>"
            f"<td>{utterance_ids}</td>"
            f"<td>{word_ids}</td>"
            f"<td>{_format_dependencies(segment)}</td>"
            "</tr>"
        )
    return "".join(rows)


def render_segmentation_debug_html(
    segments: tuple[SemanticSegment, ...],
) -> str:
    """Render a deterministic standalone HTML segmentation report."""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MiniCut Segmentation Debug</title>
<style>
:root {{ color-scheme: light dark; font-family: system-ui, sans-serif; }}
body {{ margin: 24px; }}
h1 {{ font-size: 1.4rem; }}
.timeline {{ position: relative; height: 48px; background: CanvasText; opacity: .85; }}
.segment-bar {{ position: absolute; top: 6px; height: 36px; min-width: 2px;
  overflow: hidden; background: Highlight; color: HighlightText; font-size: 11px; }}
table {{ width: 100%; margin-top: 20px; border-collapse: collapse; }}
th, td {{ padding: 8px; border: 1px solid GrayText; text-align: left; vertical-align: top; }}
th {{ white-space: nowrap; }}
code {{ overflow-wrap: anywhere; }}
.empty {{ padding: 16px; border: 1px dashed GrayText; }}
</style>
</head>
<body>
<h1>MiniCut Segmentation Debug</h1>
{_timeline_bars(segments)}
<table>
<thead><tr><th>Segment</th><th>Time</th><th>Text</th><th>Labels</th><th>Utterances</th><th>Words</th><th>Context</th></tr></thead>
<tbody>{_segment_rows(segments)}</tbody>
</table>
</body>
</html>
"""


def export_segmentation_debug(
    segments: tuple[SemanticSegment, ...],
    destination: Path,
) -> Path:
    """Write a standalone UTF-8 segmentation report."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(render_segmentation_debug_html(segments), encoding="utf-8")
    return destination


__all__ = ["export_segmentation_debug", "render_segmentation_debug_html"]
