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
        temporary: Path | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=".collection-",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                json.dump(collection.to_dict(), stream, ensure_ascii=False)
                stream.write("\n")
            temporary.replace(self.path)
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
