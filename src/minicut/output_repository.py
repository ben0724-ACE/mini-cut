"""Atomic local persistence separate from legacy edit-plan artifacts."""

import json
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import cast
from uuid import uuid4

from minicut.errors import ProcessingError, UserInputError
from minicut.output_plan import (
    OutputCollection,
    OutputPlan,
    validate_output_collection,
    validate_output_id,
)
from minicut.project_mutation import project_mutation_lock
from minicut.semantic_segment import SemanticSegment
from minicut.transcript import Transcript
from minicut.transcription_cache import TranscriptionCacheKey


class OutputCollectionRepository:
    def __init__(self, project_directory: Path, collection_id: str) -> None:
        validate_output_id(collection_id)
        self.project_directory = project_directory
        self.collection_id = collection_id
        self.path = (
            project_directory / ".minicut/output-collections" / f"{collection_id}.json"
        )
        self._mutation_lock = project_mutation_lock(project_directory)

    @contextmanager
    def mutation(self) -> Generator[None, None, None]:
        """Serialize a complete read/validate/write edit across repositories."""
        with self._mutation_lock:
            yield

    def write_segments(self, segments: tuple[SemanticSegment, ...]) -> None:
        self.write_json(
            self.path.with_suffix(".segments.json"), [s.to_dict() for s in segments]
        )

    def source_transcript(self, asset_id: str) -> Transcript:
        """Bind once, including legacy collections, without changing edit revisions."""
        sources = TranscriptVersionRepository(self.project_directory, asset_id)
        binding_path = self.path.with_suffix(".transcript.json")
        with sources.lock:
            if binding_path.is_file():
                try:
                    binding = json.loads(binding_path.read_text(encoding="utf-8"))
                    if binding["asset_id"] != asset_id:
                        raise ValueError("transcript binding asset mismatch")
                    return sources.read_version(binding["transcript_version"])
                except (OSError, ValueError, KeyError, TypeError) as error:
                    raise UserInputError(
                        "Bound source transcript is missing or invalid"
                    ) from error
            version, transcript = sources.latest()
            self.write_json(
                binding_path,
                {"asset_id": asset_id, "transcript_version": version},
            )
            return transcript

    def inherit_source_transcript(
        self, asset_id: str, source_collection_id: str
    ) -> None:
        """Carry the original generation input into a resumed task's collection."""
        sources = TranscriptVersionRepository(self.project_directory, asset_id)
        original = OutputCollectionRepository(
            self.project_directory, source_collection_id
        )
        original_path = original.path.with_suffix(".transcript.json")
        binding_path = self.path.with_suffix(".transcript.json")
        with sources.lock:
            # Older tasks, or tasks stopped before generation started, may not
            # have bound a transcript yet. Keep their existing recovery behavior.
            if not original_path.is_file():
                return
            original.source_transcript(asset_id)
            binding = json.loads(original_path.read_text(encoding="utf-8"))
            if binding_path.is_file():
                if json.loads(binding_path.read_text(encoding="utf-8")) != binding:
                    raise UserInputError(
                        "Resumed collection transcript binding differs"
                    )
                return
            self.write_json(binding_path, binding)

    def write(
        self, collection: OutputCollection, segments: tuple[SemanticSegment, ...]
    ) -> None:
        with self.mutation():
            self._write(collection, segments)

    def _write(
        self, collection: OutputCollection, segments: tuple[SemanticSegment, ...]
    ) -> None:
        validate_output_collection(collection, segments)
        if collection.collection_id != self.collection_id:
            raise ValueError("collection does not match repository ID")
        if self.path.is_file():
            prior = OutputCollection.from_dict(
                json.loads(self.path.read_text(encoding="utf-8"))
            )
            for plan in prior.plans:
                self.write_json(
                    self.version_path(plan.output_id, plan.revision), plan.to_dict()
                )
        self.write_json(self.path, collection.to_dict())

    def version_path(self, output_id: str, revision: int) -> Path:
        validate_output_id(output_id)
        if revision < 1:
            raise ValueError("revision must be positive")
        return (
            self.path.parent
            / f"{self.collection_id}-versions"
            / output_id
            / f"v{revision:04d}.json"
        )

    def render_record_path(self, output_id: str, revision: int) -> Path:
        validate_output_id(output_id)
        if type(revision) is not int or revision < 1:
            raise ValueError("render revision must be positive")
        return (
            self.path.parent
            / f"{self.collection_id}-renders"
            / output_id
            / f"v{revision:04d}.json"
        )

    def write_highlight_result(self, result: object) -> None:
        self.write_json(
            self.path.parent.parent
            / "highlight-results"
            / f"{self.collection_id}.json",
            result,
        )

    def write_render_record(
        self,
        output_id: str,
        revision: int,
        record: object,
        export_id: str | None = None,
    ) -> None:
        path = self.render_record_path(output_id, revision)
        if export_id is not None:
            validate_output_id(export_id)
            path = path.parent / export_id / path.name
        self.write_json(path, record)

    @staticmethod
    def write_json(path: Path, value: object) -> None:
        temporary: Path | None = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=".collection-",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                json.dump(value, stream, ensure_ascii=False)
                stream.write("\n")
            temporary.replace(path)
        except OSError as error:
            raise ProcessingError("Output collection could not be written") from error
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def read(self, segments: tuple[SemanticSegment, ...]) -> OutputCollection:
        try:
            data = cast(
                Mapping[str, object], json.loads(self.path.read_text(encoding="utf-8"))
            )
            collection = OutputCollection.from_dict(data)
            validate_output_collection(collection, segments)
            if collection.collection_id != self.collection_id:
                raise ValueError("collection ID mismatch")
            return collection
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            raise UserInputError("Output collection is missing or invalid") from error

    def read_plan(
        self,
        collection: OutputCollection,
        segments: tuple[SemanticSegment, ...],
        output_id: str,
        revision: int | None = None,
        *,
        require_current: bool = False,
    ) -> OutputPlan:
        """Resolve a saved revision and validate its identity and source references.

        Callers hold mutation() across reading the collection and its history.
        """
        validate_output_id(output_id)
        current = next((p for p in collection.plans if p.output_id == output_id), None)
        if current is None:
            raise UserInputError("Output plan does not exist")
        if revision is not None and (type(revision) is not int or revision < 1):
            raise UserInputError("Output revision must be positive")
        if revision is None or revision == current.revision:
            return current
        if require_current:
            raise UserInputError("作品版本已变更，请刷新后重试")
        if revision > current.revision:
            raise UserInputError("Requested output version is missing or invalid")
        try:
            plan = OutputPlan.from_dict(
                json.loads(
                    self.version_path(output_id, revision).read_text(encoding="utf-8")
                )
            )
            if plan.output_id != output_id or plan.revision != revision:
                raise ValueError("output version identity mismatch")
            validate_output_collection(replace(collection, plans=(plan,)), segments)
            return plan
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            raise UserInputError(
                "Requested output version is missing or invalid"
            ) from error

    def read_versions(
        self,
        collection: OutputCollection,
        segments: tuple[SemanticSegment, ...],
        output_id: str,
    ) -> tuple[OutputPlan, ...]:
        """Read history under the caller's mutation boundary using the same checks."""
        current = self.read_plan(collection, segments, output_id)
        plans: list[OutputPlan] = []
        for path in sorted(self.version_path(output_id, 1).parent.glob("v*.json")):
            try:
                revision = int(path.stem[1:])
            except ValueError as error:
                raise UserInputError("Output history filename is invalid") from error
            if revision < current.revision:
                plans.append(self.read_plan(collection, segments, output_id, revision))
        return tuple(sorted((*plans, current), key=lambda plan: plan.revision))


class TranscriptVersionRepository:
    """Keep full word-level versions while retaining the latest keyed cache."""

    def __init__(self, project_directory: Path, asset_id: str) -> None:
        validate_output_id(asset_id)
        self.project_directory = project_directory
        self.asset_id = asset_id
        self.cache_path = (
            project_directory / ".minicut/transcripts" / f"{asset_id}.json"
        )
        self.lock = project_mutation_lock(project_directory)

    def version_path(self, version: str) -> Path:
        validate_output_id(version)
        return (
            self.project_directory
            / ".minicut/transcript-versions"
            / self.asset_id
            / f"{version}.json"
        )

    def read_version(self, version: str) -> Transcript:
        try:
            transcript = Transcript.from_dict(
                json.loads(self.version_path(version).read_text(encoding="utf-8"))
            )
            if transcript.source.asset_id != self.asset_id:
                raise ValueError("transcript asset mismatch")
            return transcript
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise UserInputError(
                "Source transcript version is missing or invalid"
            ) from error

    def _snapshot(self, transcript: Transcript) -> str:
        if transcript.source.asset_id != self.asset_id:
            raise UserInputError("Transcript asset does not match")
        version = uuid4().hex
        OutputCollectionRepository.write_json(
            self.version_path(version), transcript.to_dict()
        )
        return version

    def latest(self) -> tuple[str, Transcript]:
        with self.lock:
            try:
                data = json.loads(self.cache_path.read_text(encoding="utf-8"))
                version = data.get("transcript_version")
                if version is not None:
                    return version, self.read_version(version)
                transcript = Transcript.from_dict(data["transcript"])
                # Legacy caches stay byte-for-byte unchanged when first bound.
                return self._snapshot(transcript), transcript
            except (OSError, ValueError, KeyError, TypeError) as error:
                raise UserInputError(
                    "Source transcript is missing or invalid"
                ) from error

    def publish(self, key: TranscriptionCacheKey, transcript: Transcript) -> None:
        with self.lock:
            if self.cache_path.is_file():
                # Archive before replacement, even if no collection was opened.
                version, _ = self.latest()
                directory = self.project_directory / ".minicut/output-collections"
                for path in directory.glob("*.json"):
                    data = json.loads(path.read_text(encoding="utf-8"))
                    if not isinstance(data, dict) or "collection_id" not in data:
                        continue
                    payload = cast(dict[str, object], data)
                    if payload.get("asset_id") != self.asset_id:
                        continue
                    repository = OutputCollectionRepository(
                        self.project_directory, cast(str, payload["collection_id"])
                    )
                    binding_path = repository.path.with_suffix(".transcript.json")
                    if not binding_path.is_file():
                        OutputCollectionRepository.write_json(
                            binding_path,
                            {"asset_id": self.asset_id, "transcript_version": version},
                        )
            version = self._snapshot(transcript)
            OutputCollectionRepository.write_json(
                self.cache_path,
                {
                    "key": key.to_dict(),
                    "transcript": transcript.to_dict(),
                    "transcript_version": version,
                },
            )
