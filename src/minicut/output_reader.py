"""Read saved outputs and their bound source data through one local boundary."""

import json
from dataclasses import dataclass
from pathlib import Path

from minicut.errors import UserInputError
from minicut.highlight_workflow import attach_continuation_context
from minicut.output_plan import OutputCollection, OutputPlan, validate_output_id
from minicut.output_repository import OutputCollectionRepository
from minicut.segmentation import build_utterances
from minicut.semantic_segment import SemanticSegment
from minicut.semantic_segmentation import (
    build_rule_based_segments,
    mark_segment_candidates,
)
from minicut.text_normalization import normalize_transcript_words
from minicut.transcript import Transcript


@dataclass(frozen=True, slots=True)
class OutputSource:
    collection: OutputCollection
    segments: tuple[SemanticSegment, ...]
    transcript: Transcript


@dataclass(frozen=True, slots=True)
class SavedOutput:
    source: OutputSource
    plan: OutputPlan


@dataclass(frozen=True, slots=True)
class OutputHistory:
    source: OutputSource
    plans: tuple[OutputPlan, ...]


def source_transcript(
    project: Path, asset_id: str, collection_id: str | None = None
) -> Transcript:
    if collection_id is not None:
        return OutputCollectionRepository(project, collection_id).source_transcript(
            asset_id
        )
    try:
        data = json.loads(
            (project / ".minicut/transcripts" / f"{asset_id}.json").read_text(
                encoding="utf-8"
            )
        )
        return Transcript.from_dict(data["transcript"])
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise UserInputError("Source transcript is missing or invalid") from error


def _segments(
    transcript: Transcript, repository: OutputCollectionRepository | None
) -> tuple[SemanticSegment, ...]:
    if repository is not None:
        path = repository.path.with_suffix(".segments.json")
        if path.is_file():
            try:
                return tuple(
                    SemanticSegment.from_dict(row)
                    for row in json.loads(path.read_text(encoding="utf-8"))
                )
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
                raise UserInputError("Saved source segments are invalid") from error
    utterances = transcript.utterances or build_utterances(
        transcript, normalize_transcript_words(transcript)
    )
    return attach_continuation_context(
        mark_segment_candidates(build_rule_based_segments(transcript, utterances))
    )


def source_segments(
    project: Path, asset: str, collection_id: str | None = None
) -> tuple[SemanticSegment, ...]:
    if collection_id is None:
        return _segments(source_transcript(project, asset), None)
    repository = OutputCollectionRepository(project, collection_id)
    with repository.mutation():
        return _segments(repository.source_transcript(asset), repository)


class OutputReader:
    def __init__(self, project: Path, collection_id: str) -> None:
        self.repository = OutputCollectionRepository(project, collection_id)

    def read(self) -> OutputSource:
        """Resolve legacy bindings once; never replace a missing bound version."""
        with self.repository.mutation():
            try:
                data = json.loads(self.repository.path.read_text(encoding="utf-8"))
                asset_id = data["asset_id"]
                validate_output_id(asset_id)
            except (OSError, ValueError, KeyError, TypeError) as error:
                raise UserInputError(
                    "Output collection is missing or invalid"
                ) from error
            transcript = self.repository.source_transcript(asset_id)
            segments = _segments(transcript, self.repository)
            collection = self.repository.read(segments)
            return OutputSource(collection, segments, transcript)

    def output(
        self,
        output_id: str,
        revision: int | None = None,
        *,
        require_current: bool = False,
    ) -> SavedOutput:
        with self.repository.mutation():
            source = self.read()
            plan = self.repository.read_plan(
                source.collection,
                source.segments,
                output_id,
                revision,
                require_current=require_current,
            )
            return SavedOutput(source, plan)

    def history(self, output_id: str) -> OutputHistory:
        with self.repository.mutation():
            source = self.read()
            plans = self.repository.read_versions(
                source.collection, source.segments, output_id
            )
            return OutputHistory(source, plans)
