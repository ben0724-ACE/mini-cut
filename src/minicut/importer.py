"""Application service for importing source media into a local project."""

from pathlib import Path
from typing import Protocol
from uuid import uuid4

from minicut.errors import ProcessingError, UserInputError
from minicut.media import MediaAsset, classify_media, fingerprint_media
from minicut.probe import ProbeResult, probe_media
from minicut.project import ProjectRepository


class MediaProber(Protocol):
    """Callable boundary for reading normalized media metadata."""

    def __call__(self, source_path: str | Path) -> ProbeResult:
        """Return normalized metadata for one media file."""
        ...


class MediaFingerprinter(Protocol):
    """Callable boundary for identifying media content."""

    def __call__(self, source_path: str | Path) -> str:
        """Return a stable identifier for the complete file content."""
        ...


class AssetIdGenerator(Protocol):
    """Callable boundary for generating candidate asset identifiers."""

    def __call__(self) -> str:
        """Return one candidate asset identifier."""
        ...


def _generate_asset_id() -> str:
    return uuid4().hex


def import_media(
    repository: ProjectRepository,
    source_path: str | Path,
    *,
    mime_type: str | None = None,
    probe: MediaProber = probe_media,
    fingerprinter: MediaFingerprinter = fingerprint_media,
    generate_asset_id: AssetIdGenerator = _generate_asset_id,
) -> MediaAsset:
    """Read source metadata and register one project asset without copying it."""
    source = Path(source_path)
    if not source.is_file():
        raise UserInputError("Media file does not exist")
    classify_media(str(source), mime_type)

    try:
        content_fingerprint = fingerprinter(source)
    except OSError as error:
        raise ProcessingError("Media file could not be read") from error

    probe_result = probe(source)
    candidate = MediaAsset(
        asset_id=generate_asset_id(),
        source_path=str(source),
        duration_ms=probe_result.duration_ms,
        streams=probe_result.streams,
        content_fingerprint=content_fingerprint,
    )
    return repository.add_asset(candidate)


__all__ = ["import_media"]
