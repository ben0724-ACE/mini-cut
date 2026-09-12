"""Local project manifest domain model."""

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import cast

from minicut.errors import ProcessingError, UserInputError
from minicut.media import MediaAsset

MANIFEST_SCHEMA_VERSION = 1


@dataclass(slots=True)
class ProjectManifest:
    """Versioned, JSON-compatible state for a MiniCut project."""

    project_id: str
    assets: tuple[MediaAsset, ...] = ()
    schema_version: int = MANIFEST_SCHEMA_VERSION
    name: str | None = None

    def __post_init__(self) -> None:
        if not self.project_id.strip():
            raise ValueError("project_id must not be blank")
        if self.name is not None and (
            type(self.name) is not str or not self.name.strip()
        ):
            raise ValueError("project name must not be blank")
        if self.schema_version != MANIFEST_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported manifest schema version: {self.schema_version}"
            )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""
        result: dict[str, object] = {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "assets": [asset.to_dict() for asset in self.assets],
        }
        if self.name is not None:
            result["name"] = self.name
        return result

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "ProjectManifest":
        """Restore a manifest from a JSON-compatible mapping."""
        assets = cast(list[dict[str, object]], data["assets"])
        return cls(
            schema_version=cast(int, data["schema_version"]),
            project_id=cast(str, data["project_id"]),
            assets=tuple(MediaAsset.from_dict(asset) for asset in assets),
            name=cast(str | None, data.get("name")),
        )


FileReplacer = Callable[[Path, Path], None]


def _replace_file(source: Path, destination: Path) -> None:
    source.replace(destination)


class ProjectRepository:
    """Persist one project manifest in a local directory."""

    def __init__(
        self,
        project_directory: str | Path,
        *,
        replace_file: FileReplacer = _replace_file,
    ) -> None:
        self.project_directory = Path(project_directory)
        self.manifest_path = self.project_directory / "manifest.json"
        self._replace_file = replace_file

    def create(self, manifest: ProjectManifest) -> None:
        """Create a new manifest without replacing an existing project."""
        self.project_directory.mkdir(parents=True, exist_ok=True)
        if self.manifest_path.exists():
            raise UserInputError("Project manifest already exists")
        try:
            self._write(manifest)
        except OSError as error:
            raise ProcessingError("Project manifest could not be created") from error

    def read(self) -> ProjectManifest:
        """Read the current project manifest."""
        if not self.manifest_path.is_file():
            raise UserInputError("Project manifest does not exist")
        try:
            data = cast(
                dict[str, object],
                json.loads(self.manifest_path.read_text(encoding="utf-8")),
            )
            return ProjectManifest.from_dict(data)
        except (AttributeError, KeyError, TypeError, UnicodeError, ValueError) as error:
            raise ProcessingError(
                "Project manifest is invalid or unsupported"
            ) from error

    def update(self, manifest: ProjectManifest) -> None:
        """Atomically replace an existing project manifest."""
        if not self.manifest_path.is_file():
            raise UserInputError("Project manifest does not exist")
        try:
            self._write(manifest)
        except OSError as error:
            raise ProcessingError("Project manifest could not be updated") from error

    def add_asset(self, asset: MediaAsset) -> MediaAsset:
        """Register new content or return the matching existing asset."""
        manifest = self.read()
        for existing_asset in manifest.assets:
            if existing_asset.content_fingerprint == asset.content_fingerprint:
                return existing_asset

        for existing_asset in manifest.assets:
            if existing_asset.asset_id == asset.asset_id:
                raise UserInputError("Project asset ID already exists")

        updated_manifest = ProjectManifest(
            project_id=manifest.project_id,
            assets=(*manifest.assets, asset),
            schema_version=manifest.schema_version,
            name=manifest.name,
        )
        self.update(updated_manifest)
        return asset

    def _write(self, manifest: ProjectManifest) -> None:
        temporary_path: Path | None = None
        try:
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.project_directory,
                prefix=".manifest-",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                json.dump(manifest.to_dict(), temporary_file, ensure_ascii=False)
                temporary_file.write("\n")
                temporary_path = Path(temporary_file.name)
            self._replace_file(temporary_path, self.manifest_path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)


__all__ = [
    "MANIFEST_SCHEMA_VERSION",
    "FileReplacer",
    "ProjectManifest",
    "ProjectRepository",
]
