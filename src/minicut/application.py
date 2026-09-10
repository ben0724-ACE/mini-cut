"""Application use cases orchestrating MiniCut domain services."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from minicut.errors import UserInputError
from minicut.importer import import_media
from minicut.media import MediaAsset
from minicut.mlx_whisper import (
    MlxWhisperConfig,
    map_mlx_transcription,
    transcribe_with_mlx,
)
from minicut.open_source_whisper import (
    OpenSourceWhisperConfig,
    map_open_source_whisper_transcription,
    transcribe_with_open_source_whisper,
)
from minicut.project import ProjectManifest, ProjectRepository
from minicut.transcript import Transcript
from minicut.transcription_cache import (
    TranscriptCacheRepository,
    TranscriptionCacheKey,
    cache_key_for_mlx,
    cache_key_for_open_source_whisper,
)


@dataclass(frozen=True, slots=True)
class InitProjectRequest:
    """Validated input required to initialize a local project."""

    project_directory: Path
    project_id: str


@dataclass(frozen=True, slots=True)
class InitProjectResult:
    """User-facing identity of a newly initialized project."""

    project_directory: Path
    project_id: str


class InitProjectOperation(Protocol):
    """Callable application boundary used by the CLI."""

    def execute(self, request: InitProjectRequest) -> InitProjectResult: ...


class InitProjectUseCase:
    """Create the initial project manifest through the project repository."""

    def execute(self, request: InitProjectRequest) -> InitProjectResult:
        project_id = request.project_id.strip()
        if not project_id:
            raise UserInputError("Project ID must not be blank")
        repository = ProjectRepository(request.project_directory)
        repository.create(ProjectManifest(project_id=project_id))
        return InitProjectResult(request.project_directory.absolute(), project_id)


@dataclass(frozen=True, slots=True)
class TranscribeRequest:
    project_directory: Path
    source_path: Path
    provider: str
    model: str
    language: str


@dataclass(frozen=True, slots=True)
class TranscribeResult:
    transcript_id: str
    asset_id: str
    word_count: int


class TranscribeOperation(Protocol):
    def execute(self, request: TranscribeRequest) -> TranscribeResult: ...


class AssetImporter(Protocol):
    def __call__(
        self, repository: ProjectRepository, source_path: str | Path
    ) -> MediaAsset: ...


class AssetTranscriber(Protocol):
    def __call__(self, asset: MediaAsset, request: TranscribeRequest) -> Transcript: ...


def _transcription_key(
    asset: MediaAsset, request: TranscribeRequest
) -> TranscriptionCacheKey:
    if request.provider == "mlx":
        config = MlxWhisperConfig(request.model, request.language)
        return cache_key_for_mlx(asset.content_fingerprint, config)
    if request.provider == "whisper":
        config = OpenSourceWhisperConfig(request.model, request.language)
        return cache_key_for_open_source_whisper(asset.content_fingerprint, config)
    raise UserInputError("Unsupported transcription provider")


def _transcribe_asset(asset: MediaAsset, request: TranscribeRequest) -> Transcript:
    if request.provider == "mlx":
        config = MlxWhisperConfig(request.model, request.language)
        response = transcribe_with_mlx(asset.source_path, config)
        return map_mlx_transcription(response, asset_id=asset.asset_id, config=config)
    if request.provider == "whisper":
        config = OpenSourceWhisperConfig(request.model, request.language)
        response = transcribe_with_open_source_whisper(asset.source_path, config)
        return map_open_source_whisper_transcription(
            response, asset_id=asset.asset_id, config=config
        )
    raise UserInputError("Unsupported transcription provider")


class TranscribeProjectUseCase:
    def __init__(
        self,
        *,
        importer: AssetImporter = import_media,
        transcriber: AssetTranscriber = _transcribe_asset,
    ) -> None:
        self._importer = importer
        self._transcriber = transcriber

    def execute(self, request: TranscribeRequest) -> TranscribeResult:
        repository = ProjectRepository(request.project_directory)
        repository.read()
        asset = self._importer(repository, request.source_path)
        cache = TranscriptCacheRepository(
            request.project_directory
            / ".minicut"
            / "transcripts"
            / f"{asset.asset_id}.json"
        )

        key = _transcription_key(asset, request)
        transcript = cache.read(key)
        if transcript is None:
            transcript = self._transcriber(asset, request)
            cache.write(key, transcript)
        return TranscribeResult(
            transcript.transcript_id, asset.asset_id, len(transcript.words)
        )


__all__ = [
    "InitProjectOperation",
    "InitProjectRequest",
    "InitProjectResult",
    "InitProjectUseCase",
    "TranscribeOperation",
    "TranscribeProjectUseCase",
    "TranscribeRequest",
    "TranscribeResult",
]
