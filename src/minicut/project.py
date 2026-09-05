"""Local project manifest domain model."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from minicut.media import MediaAsset

MANIFEST_SCHEMA_VERSION = 1


@dataclass(slots=True)
class ProjectManifest:
    """Versioned, JSON-compatible state for a MiniCut project."""

    project_id: str
    assets: tuple[MediaAsset, ...] = ()
    schema_version: int = MANIFEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.project_id.strip():
            raise ValueError("project_id must not be blank")
        if self.schema_version != MANIFEST_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported manifest schema version: {self.schema_version}"
            )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation."""
        return {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "assets": [asset.to_dict() for asset in self.assets],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "ProjectManifest":
        """Restore a manifest from a JSON-compatible mapping."""
        assets = cast(list[dict[str, object]], data["assets"])
        return cls(
            schema_version=cast(int, data["schema_version"]),
            project_id=cast(str, data["project_id"]),
            assets=tuple(MediaAsset.from_dict(asset) for asset in assets),
        )


__all__ = ["MANIFEST_SCHEMA_VERSION", "ProjectManifest"]
