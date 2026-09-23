"""Split editing items at ASR sentence boundaries without removing source time."""

from dataclasses import replace

from minicut.output_plan import OutputItem, OutputPlan
from minicut.semantic_segment import SemanticSegment
from minicut.sentence_boundaries import sentence_segments
from minicut.transcript import Transcript


def split_output_sentences(
    plan: OutputPlan, segments: tuple[SemanticSegment, ...], transcript: Transcript
) -> OutputPlan:
    by_id = {s.segment_id: s for s in segments}
    # Prefer punctuation/pause boundaries; Whisper utterances also provide useful
    # editing units when the recognizer emits no sentence punctuation.
    boundaries = {s.start_ms for s in sentence_segments(transcript)}
    boundaries.update(u.start_ms for u in transcript.utterances)
    items: list[OutputItem] = []
    for item in plan.items:
        source = by_id[item.segment_id]
        start = (
            source.start_ms if item.source_start_ms is None else item.source_start_ms
        )
        end = source.end_ms if item.source_end_ms is None else item.source_end_ms
        first_word = next(
            (w for w in transcript.words if w.end_ms > start and w.start_ms < end), None
        )
        cuts = [
            start,
            *sorted(
                t
                for t in boundaries
                if start < t < end
                and first_word is not None
                and t > first_word.start_ms
            ),
            end,
        ]
        if len(cuts) == 2 or item.deleted:
            items.append(item)
            continue
        for index, (first, last) in enumerate(zip(cuts, cuts[1:], strict=False)):
            items.append(
                replace(
                    item,
                    instance_id=f"{item.instance_id}-sentence-{index}",
                    source_start_ms=first,
                    source_end_ms=last,
                    display_text=None,
                    translation_text=None,
                )
            )
    return replace(plan, items=tuple(items))
