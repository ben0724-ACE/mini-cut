"""Deterministic candidate selection for a complete narrative outline."""

from dataclasses import dataclass
from enum import StrEnum

from minicut.edit_plan import ContentRequirement, EditBrief
from minicut.local_analysis import LocalSegmentAnalysis, SegmentClassification
from minicut.narrative_outline import NarrativeOutline, NarrativeSection
from minicut.semantic_segment import (
    SemanticSegment,
    validate_segment_context_dependencies,
)


class NarrativeRole(StrEnum):
    """Narrative roles that must retain at least one evidence Segment."""

    OPENING = "opening"
    CORE_POINT = "core_point"
    CONCLUSION = "conclusion"


@dataclass(frozen=True, slots=True)
class NarrativeCoverage:
    """Viable evidence roots for one narrative role or core point."""

    role: NarrativeRole
    ordinal: int
    segment_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.ordinal < 0:
            raise ValueError("narrative coverage ordinal must not be negative")
        if not self.segment_ids:
            raise ValueError("narrative coverage must contain evidence")
        if len(set(self.segment_ids)) != len(self.segment_ids):
            raise ValueError("narrative coverage Segment IDs must be unique")


@dataclass(frozen=True, slots=True)
class NarrativeCandidate:
    """One candidate with ranking metadata and direct dependencies."""

    segment_id: str
    importance: float
    dependency_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NarrativeCandidateSelection:
    """Candidate pool, mandatory content, and narrative coverage constraints."""

    candidates: tuple[NarrativeCandidate, ...]
    required_ids: tuple[str, ...]
    coverages: tuple[NarrativeCoverage, ...]

    def __post_init__(self) -> None:
        candidate_ids = self.candidate_ids
        if len(set(candidate_ids)) != len(candidate_ids):
            raise ValueError("narrative candidate Segment IDs must be unique")
        if not set(self.required_ids) <= set(candidate_ids):
            raise ValueError("required Segment IDs must be narrative candidates")
        if any(
            not set(coverage.segment_ids) <= set(candidate_ids)
            for coverage in self.coverages
        ):
            raise ValueError("coverage evidence must be narrative candidates")

    @property
    def candidate_ids(self) -> tuple[str, ...]:
        """Return candidate IDs in source order."""
        return tuple(candidate.segment_id for candidate in self.candidates)

    def dependencies_for(self, segment_id: str) -> tuple[str, ...]:
        """Return direct dependencies for a known candidate."""
        for candidate in self.candidates:
            if candidate.segment_id == segment_id:
                return candidate.dependency_ids
        raise ValueError("unknown narrative candidate Segment ID")


def _requirement_ids(
    requirements: tuple[ContentRequirement, ...],
) -> set[str]:
    return {
        segment_id
        for requirement in requirements
        for segment_id in requirement.segment_ids
    }


def _outline_sections(
    outline: NarrativeOutline,
) -> tuple[tuple[NarrativeRole, int, NarrativeSection], ...]:
    core_sections = tuple(
        (NarrativeRole.CORE_POINT, ordinal, section)
        for ordinal, section in enumerate(outline.core_points)
    )
    return (
        (NarrativeRole.OPENING, 0, outline.opening),
        *core_sections,
        (NarrativeRole.CONCLUSION, 0, outline.conclusion),
    )


def select_narrative_candidates(
    brief: EditBrief,
    segments: tuple[SemanticSegment, ...],
    analyses: tuple[LocalSegmentAnalysis, ...],
    outline: NarrativeOutline,
) -> NarrativeCandidateSelection:
    """Select viable narrative evidence while preserving dependency closure."""
    validate_segment_context_dependencies(segments)
    segment_ids = tuple(segment.segment_id for segment in segments)
    known_ids = set(segment_ids)
    analysis_ids = tuple(analysis.segment_id for analysis in analyses)
    if len(set(analysis_ids)) != len(analysis_ids):
        raise ValueError("local analyses contain duplicate Segment IDs")
    if set(analysis_ids) != known_ids:
        raise ValueError("local analyses must exactly cover the source Segments")

    sections = _outline_sections(outline)
    outline_ids = {
        segment_id for _, _, section in sections for segment_id in section.segment_ids
    }
    if not outline_ids <= known_ids:
        raise ValueError("narrative outline references an unknown Segment ID")

    must_keep_ids = _requirement_ids(brief.must_keep)
    must_remove_ids = _requirement_ids(brief.must_remove)
    if not (must_keep_ids | must_remove_ids) <= known_ids:
        raise ValueError("content requirement references an unknown Segment ID")
    if must_keep_ids & must_remove_ids:
        raise ValueError("must_keep and must_remove requirements conflict")

    analyses_by_id = {analysis.segment_id: analysis for analysis in analyses}
    segments_by_id = {segment.segment_id: segment for segment in segments}
    dependency_map: dict[str, tuple[str, ...]] = {}
    for segment_id in segment_ids:
        dependency_set = set(analyses_by_id[segment_id].dependency_ids) | {
            dependency.segment_id
            for dependency in segments_by_id[segment_id].context_dependencies
        }
        if not dependency_set <= known_ids:
            raise ValueError("local analyses reference an unknown dependency")
        dependency_map[segment_id] = tuple(
            candidate_id
            for candidate_id in segment_ids
            if candidate_id in dependency_set
        )

    def dependency_closure(root_id: str) -> set[str]:
        closure: set[str] = set()
        pending = [root_id]
        while pending:
            segment_id = pending.pop()
            if segment_id in closure:
                continue
            closure.add(segment_id)
            pending.extend(dependency_map[segment_id])
        return closure

    required_set = {
        dependency_id
        for segment_id in must_keep_ids
        for dependency_id in dependency_closure(segment_id)
    }
    if required_set & must_remove_ids:
        raise ValueError("must_remove requirement conflicts with required context")

    candidate_set = set(required_set)
    coverages: list[NarrativeCoverage] = []
    for role, ordinal, section in sections:
        viable_ids = tuple(
            segment_id
            for segment_id in section.segment_ids
            if (
                analyses_by_id[segment_id].classification
                is SegmentClassification.CONTENT
                or segment_id in required_set
            )
            and not dependency_closure(segment_id) & must_remove_ids
        )
        if not viable_ids:
            raise ValueError(f"narrative {role.value} has no viable evidence")
        coverages.append(NarrativeCoverage(role, ordinal, viable_ids))
        for segment_id in viable_ids:
            candidate_set.update(dependency_closure(segment_id))

    candidates = tuple(
        NarrativeCandidate(
            segment_id,
            analyses_by_id[segment_id].importance,
            dependency_map[segment_id],
        )
        for segment_id in segment_ids
        if segment_id in candidate_set
    )
    required_ids = tuple(
        segment_id for segment_id in segment_ids if segment_id in required_set
    )
    return NarrativeCandidateSelection(candidates, required_ids, tuple(coverages))


__all__ = [
    "NarrativeCandidate",
    "NarrativeCandidateSelection",
    "NarrativeCoverage",
    "NarrativeRole",
    "select_narrative_candidates",
]
