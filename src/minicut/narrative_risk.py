"""Conservative detection of narrative breaks after duration selection."""

from dataclasses import dataclass
from enum import StrEnum

from minicut.narrative_selection import (
    NarrativeCandidateSelection,
    TargetDurationSelection,
)
from minicut.semantic_segment import (
    SemanticSegment,
    validate_segment_context_dependencies,
)

_REFERENCE_PREFIXES = (
    "如前所述",
    "前面提到",
    "刚才提到",
    "上述",
    "前述",
    "这个数据",
    "该结果",
)
_CAUSAL_PREFIXES = ("因此", "所以", "因而", "由此", "于是")
_PRONOUN_PREFIXES = (
    "它们",
    "他们",
    "她们",
    "这个",
    "这些",
    "那个",
    "那些",
    "它",
    "他",
    "她",
    "这",
    "那",
    "其",
)


class NarrativeBreakKind(StrEnum):
    """Supported explainable narrative-break categories."""

    PRONOUN = "pronoun"
    CAUSAL = "causal"
    REFERENCE = "reference"


@dataclass(frozen=True, slots=True)
class NarrativeBreakRisk:
    """One selected Segment whose preceding context may be broken."""

    segment_id: str
    kind: NarrativeBreakKind
    missing_context_ids: tuple[str, ...]
    explanation: str

    def __post_init__(self) -> None:
        if not self.segment_id.strip():
            raise ValueError("narrative break Segment ID must not be blank")
        if any(not segment_id.strip() for segment_id in self.missing_context_ids):
            raise ValueError("missing context Segment IDs must not be blank")
        if len(set(self.missing_context_ids)) != len(self.missing_context_ids):
            raise ValueError("missing context Segment IDs must be unique")
        if not self.explanation.strip():
            raise ValueError("narrative break explanation must not be blank")


def _lexical_break_kind(text: str) -> NarrativeBreakKind | None:
    normalized = text.lstrip(" \t\r\n，,。.!！?？：:；;")
    if normalized.startswith(_REFERENCE_PREFIXES):
        return NarrativeBreakKind.REFERENCE
    if normalized.startswith(_CAUSAL_PREFIXES):
        return NarrativeBreakKind.CAUSAL
    if normalized.startswith(_PRONOUN_PREFIXES):
        return NarrativeBreakKind.PRONOUN
    return None


def detect_narrative_break_risks(
    segments: tuple[SemanticSegment, ...],
    candidates: NarrativeCandidateSelection,
    duration_selection: TargetDurationSelection,
) -> tuple[NarrativeBreakRisk, ...]:
    """Report declared or lexical context breaks without changing the selection."""
    validate_segment_context_dependencies(segments)
    source_ids = tuple(segment.segment_id for segment in segments)
    known_ids = set(source_ids)
    selected_ids = set(duration_selection.selected_ids)
    if not selected_ids <= known_ids:
        raise ValueError("duration selection references an unknown Segment ID")
    if not selected_ids <= set(candidates.candidate_ids):
        raise ValueError("duration selection contains a non-candidate Segment")

    candidate_by_id = {
        candidate.segment_id: candidate for candidate in candidates.candidates
    }
    risks: list[NarrativeBreakRisk] = []
    for ordinal, segment in enumerate(segments):
        if segment.segment_id not in selected_ids:
            continue
        missing_dependencies = tuple(
            dependency_id
            for dependency_id in candidate_by_id[segment.segment_id].dependency_ids
            if dependency_id not in selected_ids
        )
        if missing_dependencies:
            risks.append(
                NarrativeBreakRisk(
                    segment.segment_id,
                    NarrativeBreakKind.REFERENCE,
                    missing_dependencies,
                    "A declared dependency is missing from the selected narrative.",
                )
            )
            continue

        if ordinal == 0 or source_ids[ordinal - 1] in selected_ids:
            continue
        kind = _lexical_break_kind(segment.text)
        if kind is None:
            continue
        risks.append(
            NarrativeBreakRisk(
                segment.segment_id,
                kind,
                (source_ids[ordinal - 1],),
                f"The selected Segment starts with a {kind.value} reference after "
                "its preceding source Segment was removed.",
            )
        )
    return tuple(risks)


__all__ = [
    "NarrativeBreakKind",
    "NarrativeBreakRisk",
    "detect_narrative_break_risks",
]
