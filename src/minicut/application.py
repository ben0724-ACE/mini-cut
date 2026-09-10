"""Application use cases orchestrating MiniCut domain services."""

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Protocol, cast

from minicut.deepseek_provider import create_deepseek_planner_from_env
from minicut.edit_plan import EditBrief, EditIntensity, EditPlan
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
from minicut.rule_planner import RulePlanner
from minicut.segmentation import build_utterances
from minicut.semantic_segment import SemanticSegment
from minicut.semantic_segmentation import (
    build_rule_based_segments,
    mark_segment_candidates,
)
from minicut.text_normalization import normalize_transcript_words
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


@dataclass(frozen=True, slots=True)
class PlanRequest:
    project_directory: Path
    asset_id: str
    target_duration_ms: int
    intensity: EditIntensity
    style: str
    planner: str


@dataclass(frozen=True, slots=True)
class PlanResult:
    asset_id: str
    kept_segments: int
    deleted_segments: int
    artifact_path: Path


class PlanOperation(Protocol):
    def execute(self, request: PlanRequest) -> PlanResult: ...


class EditPlanner(Protocol):
    def __call__(
        self,
        request: PlanRequest,
        brief: EditBrief,
        segments: tuple[SemanticSegment, ...],
    ) -> EditPlan: ...


def _plan_edit(
    request: PlanRequest,
    brief: EditBrief,
    segments: tuple[SemanticSegment, ...],
) -> EditPlan:
    if request.planner == "rule":
        return RulePlanner().plan(brief, segments)
    if request.planner == "deepseek":
        return asyncio.run(create_deepseek_planner_from_env().plan(brief, segments))
    raise UserInputError("Unsupported edit planner")


def _read_cached_transcript(project_directory: Path, asset_id: str) -> Transcript:
    path = project_directory / ".minicut" / "transcripts" / f"{asset_id}.json"
    if not path.is_file():
        raise UserInputError("Transcript artifact does not exist")
    try:
        payload = cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))
        transcript_data = cast(dict[str, object], payload["transcript"])
        return Transcript.from_dict(transcript_data)
    except (KeyError, OSError, TypeError, UnicodeError, ValueError) as error:
        raise UserInputError("Transcript artifact is invalid") from error


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}-",
            suffix=".tmp",
            delete=False,
        ) as output:
            json.dump(value, output, ensure_ascii=False)
            output.write("\n")
            temporary_path = Path(output.name)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


class PlanProjectUseCase:
    def __init__(self, *, planner: EditPlanner = _plan_edit) -> None:
        self._planner = planner

    def execute(self, request: PlanRequest) -> PlanResult:
        if request.target_duration_ms <= 0:
            raise UserInputError("Target duration must be positive")
        if not request.asset_id.strip() or not request.style.strip():
            raise UserInputError("Asset ID and style must not be blank")
        ProjectRepository(request.project_directory).read()
        transcript = _read_cached_transcript(
            request.project_directory, request.asset_id
        )
        mappings = normalize_transcript_words(transcript)
        utterances = transcript.utterances or build_utterances(transcript, mappings)
        segments = mark_segment_candidates(
            build_rule_based_segments(transcript, utterances)
        )
        brief = EditBrief(
            request.target_duration_ms,
            request.intensity,
            request.style,
            language=transcript.language,
        )
        plan = self._planner(request, brief, segments)
        artifact_path = (
            request.project_directory
            / ".minicut"
            / "plans"
            / f"{request.asset_id}.json"
        )
        _write_json(
            artifact_path,
            {
                "asset_id": request.asset_id,
                "segments": [segment.to_dict() for segment in segments],
                "plan": plan.to_dict(),
            },
        )
        kept = sum(decision.action.value == "keep" for decision in plan.decisions)
        return PlanResult(
            request.asset_id,
            kept,
            len(plan.decisions) - kept,
            artifact_path,
        )


__all__ = [
    "InitProjectOperation",
    "InitProjectRequest",
    "InitProjectResult",
    "InitProjectUseCase",
    "PlanOperation",
    "PlanProjectUseCase",
    "PlanRequest",
    "PlanResult",
    "TranscribeOperation",
    "TranscribeProjectUseCase",
    "TranscribeRequest",
    "TranscribeResult",
]
