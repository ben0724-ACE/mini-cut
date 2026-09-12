"""Atomic local persistence separate from legacy edit-plan artifacts."""

import json
from collections.abc import Mapping
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import cast

from minicut.errors import ProcessingError, UserInputError
from minicut.output_plan import (
    OutputCollection,
    validate_output_collection,
    validate_output_id,
)
from minicut.semantic_segment import SemanticSegment


class OutputCollectionRepository:
    def __init__(self, project_directory: Path, collection_id: str) -> None:
        validate_output_id(collection_id)
        self.collection_id = collection_id
        self.path = (
            project_directory / ".minicut/output-collections" / f"{collection_id}.json"
        )

    def write(
        self, collection: OutputCollection, segments: tuple[SemanticSegment, ...]
    ) -> None:
        validate_output_collection(collection, segments)
        if collection.collection_id != self.collection_id:
            raise ValueError("collection does not match repository ID")
        self._write_json(self.path, collection.to_dict())

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
        self._write_json(
            self.path.parent.parent
            / "highlight-results"
            / f"{self.collection_id}.json",
            result,
        )

    def write_render_record(
        self, output_id: str, revision: int, record: object
    ) -> None:
        self._write_json(self.render_record_path(output_id, revision), record)

    @staticmethod
    def _write_json(path: Path, value: object) -> None:
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
