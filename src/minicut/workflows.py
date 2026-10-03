"""Reusable minimal-mode workflows and durable coordination of existing tasks."""

import base64
import json
import os
import sqlite3
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Annotated, Any, Literal, Protocol
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from minicut.cover_design import (
    CoverDesign,
    CoverStore,
    design_directory,
    validate_design,
)
from minicut.cover_templates import CoverTemplateLibrary
from minicut.errors import MiniCutError
from minicut.export_settings import (
    ExportDraft,
    ExportOptions,
    ExportSettings,
    ExportSubtitleSettings,
)
from minicut.generation_presets import GenerationPresetBody, PresetRenameBody
from minicut.generation_settings import GenerationDraft, GenerationSettings
from minicut.highlight_service import read_highlights, source_segments
from minicut.output_plan import OutputPlan
from minicut.output_repository import OutputCollectionRepository
from minicut.project import ProjectRepository
from minicut.transcription_task import TranscriptionCancelled

# SQLite and task journals contain heterogeneous JSON; models below validate
# user-facing configuration before it enters the workflow.
JsonObject = dict[str, Any]


class JobWriter(Protocol):
    def __call__(
        self, path: Path, payload: JsonObject, *, create: bool = False
    ) -> None: ...


WorkflowChild = Callable[
    [str, str, JsonObject, str, Callable[[list[str]], None]], JsonObject
]

SafeId = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")]


class WorkflowTranscription(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["mlx", "whisper"] = "mlx"
    model: str = Field(default="large-v3-turbo", min_length=1, max_length=200)
    language: Literal["zh", "en"] = "zh"


class WorkflowLayout(ExportSubtitleSettings):
    hook_transition_ms: int = Field(default=300, ge=0, le=1000, strict=True)
    hook_transition_kind: Literal["fade", "tv_static"] = "fade"


class WorkflowBody(PresetRenameBody):
    generation: GenerationDraft
    transcription: WorkflowTranscription = Field(default_factory=WorkflowTranscription)
    export_options: ExportOptions = Field(default_factory=ExportOptions)
    layout: WorkflowLayout = Field(default_factory=WorkflowLayout)
    cover_template_id: SafeId | None = None
    auto_export: bool = False

    @model_validator(mode="after")
    def valid_generation(self) -> "WorkflowBody":
        GenerationPresetBody(name=self.name, draft=self.generation)
        return self

    def brief(self) -> dict[str, object]:
        draft = self.generation
        limited = draft.limit_duration and draft.preset != "clean_speech"
        return {
            "preset": draft.preset.value,
            "custom_preset_id": draft.custom_preset_id,
            "custom_preset_name": draft.custom_preset_name,
            "editing_prompt": GenerationPresetBody(
                name=self.name, draft=draft
            ).active_prompt(),
            "count": int(draft.count),
            "min_ms": round(draft.min_seconds * 1000) if limited else None,
            "max_ms": round(draft.max_seconds * 1000) if limited else None,
            "hook_ms": round(draft.hook_seconds * 1000) if draft.hook_enabled else None,
            "max_source_overlap": 1
            if draft.count == 1
            else draft.overlap_percent / 100,
            "body_mode": draft.body_mode,
            "translation_language": draft.translation_language
            if draft.translation_enabled
            else None,
            "subtitle_mode": draft.subtitle_mode,
        }


class WorkflowLibrary:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.path = root / ".minicut/workflows.sqlite3"

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=30)
        db.execute("""CREATE TABLE IF NOT EXISTS workflows (
            workflow_id TEXT PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE UNIQUE,
            definition TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
        return db

    @staticmethod
    def entry(row: tuple[str, str, str, str, str]) -> JsonObject:
        return {
            "workflow_id": row[0],
            **json.loads(row[2]),
            "name": row[1],
            "created_at": row[3],
            "updated_at": row[4],
        }

    def list(self) -> list[JsonObject]:
        if not self.path.exists():
            return []
        with self.connect() as db:
            return [
                self.public(self.entry(row))
                for row in db.execute(
                    "SELECT * FROM workflows ORDER BY name COLLATE NOCASE"
                )
            ]

    @staticmethod
    def public(entry: JsonObject) -> JsonObject:
        return {
            key: value
            for key, value in entry.items()
            if key not in {"cover_png", "cover_style"}
        }

    def get(self, identity: str) -> JsonObject:
        if self.path.exists():
            with self.connect() as db:
                row = db.execute(
                    "SELECT * FROM workflows WHERE workflow_id=?", (identity,)
                ).fetchone()
            if row:
                return self.entry(row)
        raise HTTPException(404, "工作流已删除或不存在")

    def save(self, body: WorkflowBody, identity: str | None = None) -> JsonObject:
        previous = self.get(identity) if identity else None
        definition = body.model_dump(mode="json")
        definition.update(cover_style=None, cover_png=None, cover_template_name=None)
        if body.cover_template_id:
            library = CoverTemplateLibrary(self.root)
            try:
                template = library.get(body.cover_template_id)
                definition.update(
                    cover_style=template.style.model_dump(mode="json"),
                    cover_template_name=template.name,
                )
                if template.style.background_image:
                    definition["cover_png"] = base64.b64encode(
                        library.background(template.style.background_image)
                    ).decode("ascii")
            except MiniCutError as error:
                # Updating other settings still works after the source template is deleted.
                if (
                    previous
                    and previous.get("cover_template_id") == body.cover_template_id
                ):
                    definition.update(
                        {
                            key: previous.get(key)
                            for key in (
                                "cover_style",
                                "cover_png",
                                "cover_template_name",
                            )
                        }
                    )
                else:
                    raise HTTPException(400, str(error)) from error
        identity = identity or f"workflow-{uuid4().hex}"
        now = datetime.now(UTC).isoformat()
        try:
            with self.connect() as db:
                db.execute(
                    "INSERT INTO workflows VALUES (?,?,?,?,?) ON CONFLICT(workflow_id) DO UPDATE SET name=excluded.name,definition=excluded.definition,updated_at=excluded.updated_at",
                    (
                        identity,
                        body.name,
                        json.dumps(definition, ensure_ascii=False),
                        previous["created_at"] if previous else now,
                        now,
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise HTTPException(409, "已有同名工作流，请换一个名称") from error
        return self.public(self.get(identity))

    def rename(self, identity: str, name: str) -> JsonObject:
        self.get(identity)
        try:
            with self.connect() as db:
                db.execute(
                    "UPDATE workflows SET name=?,updated_at=? WHERE workflow_id=?",
                    (name, datetime.now(UTC).isoformat(), identity),
                )
        except sqlite3.IntegrityError as error:
            raise HTTPException(409, "已有同名工作流，请换一个名称") from error
        return self.public(self.get(identity))

    def delete(self, identity: str) -> None:
        self.get(identity)
        with self.connect() as db:
            db.execute("DELETE FROM workflows WHERE workflow_id=?", (identity,))


def configure_outputs(
    project: Path, result: JsonObject, definition: JsonObject
) -> JsonObject:
    """Apply saved settings once, using ordinary output revisions and owned covers."""
    collection_id = result["collection_id"]
    if not result["outputs"]:
        return result
    segments = source_segments(project, result["asset_id"], collection_id)
    repository = OutputCollectionRepository(project, collection_id)
    collection = repository.read(segments)
    saved_layout = WorkflowLayout.model_validate(definition["layout"])
    layout = saved_layout.model_dump(exclude_none=True)
    if saved_layout.subtitle_style is not None:
        layout["subtitle_style"] = saved_layout.subtitle_style
    options = ExportOptions.model_validate(definition["export_options"])
    if options.subtitle_settings is not None:
        layout.update(options.subtitle_settings.plan_changes())
    changed = False
    plans: list[OutputPlan] = []
    for plan in collection.plans:
        if any(getattr(plan, key) != value for key, value in layout.items()):
            plan = replace(plan, revision=plan.revision + 1, **layout)
            changed = True
        plans.append(plan)
    if changed:
        repository.write(replace(collection, plans=tuple(plans)), segments)
    settings = ExportSettings(project)
    for plan in plans:
        # A resumed run does not reapply configuration to an already saved output.
        if settings.read("single", collection_id, plan.output_id)["source"] != "saved":
            settings.save(
                "single",
                collection_id,
                plan.output_id,
                ExportDraft(
                    options=options.model_copy(update={"subtitle_settings": None})
                ),
            )
        if definition.get("cover_style"):
            store = CoverStore(project, collection_id, plan.output_id)
            if store.read() is None:
                design = CoverDesign.model_validate(
                    {
                        **definition["cover_style"],
                        "title": plan.title,
                        "template_id": definition["cover_template_id"],
                        "template_name": definition["cover_template_name"],
                    }
                )
                if definition.get("cover_png"):
                    directory = design_directory(project, collection_id, plan.output_id)
                    directory.mkdir(parents=True, exist_ok=True)
                    design.background_image = uuid4().hex
                    (directory / f"{design.background_image}.png").write_bytes(
                        base64.b64decode(definition["cover_png"])
                    )
                validate_design(
                    project, collection_id, plan.output_id, plan.revision, design
                )
                store.save(design, 0)
    return read_highlights(project, collection_id)


class WorkflowRunBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: SafeId
    workflow_id: SafeId


def workflow_router(
    root: Path,
    read_job: Callable[[Path], JsonObject],
    write_job: JobWriter,
    child_task: WorkflowChild,
    cancel_child: Callable[[str, str], None],
) -> APIRouter:
    router = APIRouter()
    library = WorkflowLibrary(root)
    lock = Lock()
    active: set[tuple[str, str]] = set()

    def path(project: str, identity: str) -> Path:
        return root / project / ".minicut/jobs" / f"{identity}.json"

    def project_path(project: str) -> Path:
        try:
            ProjectRepository(root / project).read()
        except MiniCutError as error:
            raise HTTPException(404, str(error)) from error
        return root / project

    def response(job: JsonObject) -> JsonObject:
        return {key: value for key, value in job.items() if key != "request"} | {
            "asset_id": job["request"]["asset_id"],
            "workflow_name": job["request"]["definition"]["name"],
        }

    def jobs(project: str) -> list[JsonObject]:
        return [
            read_job(item) for item in (root / project / ".minicut/jobs").glob("*.json")
        ]

    @router.get("/api/workflows")
    def list_workflows(  # pyright: ignore[reportUnusedFunction]
    ) -> list[JsonObject]:
        return library.list()

    @router.post("/api/workflows", status_code=201)
    def create_workflow(  # pyright: ignore[reportUnusedFunction]
        body: WorkflowBody,
    ) -> JsonObject:
        return library.save(body)

    @router.put("/api/workflows/{identity}")
    def update_workflow(  # pyright: ignore[reportUnusedFunction]
        identity: SafeId, body: WorkflowBody
    ) -> JsonObject:
        return library.save(body, identity)

    @router.patch("/api/workflows/{identity}")
    def rename_workflow(  # pyright: ignore[reportUnusedFunction]
        identity: SafeId, body: PresetRenameBody
    ) -> JsonObject:
        return library.rename(identity, body.name)

    @router.delete("/api/workflows/{identity}")
    def delete_workflow(  # pyright: ignore[reportUnusedFunction]
        identity: SafeId,
    ) -> JsonObject:
        library.delete(identity)
        return {"deleted": True}

    def run(project: str, identity: str) -> None:
        job = read_job(path(project, identity))
        request = job["request"]
        definition = request["definition"]
        body = WorkflowBody.model_validate(
            {key: definition[key] for key in WorkflowBody.model_fields}
        )

        def save(**changes: object) -> None:
            with lock:
                cancellation = read_job(path(project, identity)).get(
                    "cancel_requested", False
                )
                job.update(changes, cancel_requested=cancellation)
                write_job(path(project, identity), job)

        def check_cancel() -> None:
            if read_job(path(project, identity)).get("cancel_requested"):
                raise TranscriptionCancelled()

        def child(kind: str, data: JsonObject, suffix: str) -> JsonObject:
            check_cancel()
            save(phase=kind)

            def started(task_ids: list[str]) -> None:
                save(child_task_ids=task_ids)
                if kind == "export":
                    save(
                        exports=[
                            {"outputId": output["output_id"], "taskId": task_id}
                            for output, task_id in zip(
                                data["outputs"], task_ids, strict=True
                            )
                        ]
                    )
                if read_job(path(project, identity)).get("cancel_requested"):
                    for task_id in task_ids:
                        cancel_child(project, task_id)

            result = child_task(project, kind, data, f"{identity}-{suffix}", started)
            check_cancel()
            return result

        try:
            save(status="running", error=None, owner_pid=os.getpid())
            child(
                "transcribe",
                {"asset_id": request["asset_id"], **body.transcription.model_dump()},
                "transcribe",
            )
            if not job.get("result"):
                GenerationSettings(root / project).save(
                    request["asset_id"], body.generation
                )
                result = child(
                    "highlights",
                    {"asset_id": request["asset_id"], **body.brief()},
                    "generate",
                )
                save(result=result)
            check_cancel()
            if not job.get("configured"):
                save(phase="configure")
                result = configure_outputs(root / project, job["result"], definition)
                save(result=result, configured=True)
            if body.auto_export and job["result"]["outputs"]:
                outputs = [
                    {
                        "collection_id": job["result"]["collection_id"],
                        "output_id": output["output_id"],
                        "revision": output["revision"],
                        **body.export_options.model_dump(),
                    }
                    for output in job["result"]["outputs"]
                ]
                exports = child("export", {"outputs": outputs}, "export")
                save(exports=exports["entries"])
            check_cancel()
            save(status="succeeded", phase="completed", child_task_ids=[])
        except TranscriptionCancelled:
            save(status="cancelled", child_task_ids=[])
        except Exception as error:
            detail = error.detail if isinstance(error, HTTPException) else str(error)
            save(
                status="failed",
                error=detail or "工作流执行失败，可继续已保存的阶段",
                child_task_ids=[],
            )
        finally:
            with lock:
                active.discard((project, identity))

    @router.get("/api/projects/{project}/workflow-run")
    def latest_run(  # pyright: ignore[reportUnusedFunction]
        project: SafeId,
    ) -> JsonObject | None:
        project_path(project)
        runs = [item for item in jobs(project) if item.get("kind") == "workflow"]
        return (
            response(max(runs, key=lambda item: item["created_at"])) if runs else None
        )

    @router.post("/api/projects/{project}/workflow-runs", status_code=202)
    def start_run(  # pyright: ignore[reportUnusedFunction]
        project: SafeId,
        body: WorkflowRunBody,
        background: BackgroundTasks,
        key: Annotated[SafeId, Header(alias="Idempotency-Key")],
    ) -> JsonObject:
        directory = project_path(project)
        if not any(
            item.asset_id == body.asset_id
            for item in ProjectRepository(directory).read().assets
        ):
            raise HTTPException(404, "素材不存在")
        with lock:
            identity = f"workflow-run-{key}"
            existing = path(project, identity)
            if existing.exists():
                job = read_job(existing)
                if (
                    job["request"]["asset_id"] != body.asset_id
                    or job["request"]["workflow_id"] != body.workflow_id
                ):
                    raise HTTPException(409, "此请求标识已被另一工作流使用")
                return response(job)
            if any(
                item.get("status") in {"pending", "running"}
                and (
                    item.get("kind") == "workflow"
                    or item.get("request", {}).get("asset_id") == body.asset_id
                )
                for item in jobs(project)
            ):
                raise HTTPException(409, "项目已有正在执行的任务，请等待完成或取消")
            job: JsonObject = {
                "task_id": identity,
                "kind": "workflow",
                "status": "pending",
                "owner_pid": os.getpid(),
                "created_at": datetime.now(UTC).isoformat(),
                "phase": "pending",
                "resumable": True,
                "request": {
                    **body.model_dump(),
                    "definition": library.get(body.workflow_id),
                },
                "result": None,
                "error": None,
                "exports": [],
                "child_task_ids": [],
            }
            write_job(existing, job, create=True)
            active.add((project, identity))
            background.add_task(run, project, identity)
            return response(job)

    @router.post(
        "/api/projects/{project}/workflow-runs/{identity}/resume", status_code=202
    )
    def resume_run(  # pyright: ignore[reportUnusedFunction]
        project: SafeId, identity: SafeId, background: BackgroundTasks
    ) -> JsonObject:
        project_path(project)
        with lock:
            job = read_job(path(project, identity))
            if job.get("kind") != "workflow":
                raise HTTPException(404, "工作流任务不存在")
            if (project, identity) in active:
                return response(job)
            if job["status"] not in {"failed", "cancelled"}:
                raise HTTPException(409, "只有失败或取消的工作流可以继续")
            if any(
                item.get("status") in {"pending", "running"} for item in jobs(project)
            ):
                raise HTTPException(409, "项目已有正在执行的任务")
            job.update(status="pending", cancel_requested=False, owner_pid=os.getpid())
            write_job(path(project, identity), job)
            active.add((project, identity))
            background.add_task(run, project, identity)
            return response(job)

    @router.post("/api/projects/{project}/workflow-runs/{identity}/cancel")
    def cancel_run(  # pyright: ignore[reportUnusedFunction]
        project: SafeId, identity: SafeId
    ) -> JsonObject:
        project_path(project)
        with lock:
            job = read_job(path(project, identity))
            if job.get("kind") != "workflow":
                raise HTTPException(404, "工作流任务不存在")
            if job["status"] in {"pending", "running"}:
                job["cancel_requested"] = True
                write_job(path(project, identity), job)
                for task_id in job.get("child_task_ids", []):
                    cancel_child(project, task_id)
            return response(job)

    return router
