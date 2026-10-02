"""Local export drafts and the cross-project export preset library."""

import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar, cast

from fastapi import APIRouter, HTTPException

from minicut.errors import MiniCutError
from minicut.export_settings import (
    ExportDraft,
    ExportPresetBody,
    ExportPresetLibrary,
    ExportSettings,
    SafeId,
)
from minicut.generation_presets import (
    PresetNameConflict,
    PresetNotFound,
    PresetRenameBody,
)
from minicut.highlight_service import read_highlights
from minicut.project import ProjectRepository

T = TypeVar("T")


def checked(operation: Callable[[], T]) -> T:
    try:
        return operation()
    except PresetNameConflict:
        raise HTTPException(409, "已有同名导出预设，请换一个名称") from None
    except PresetNotFound:
        raise HTTPException(404, "导出预设已删除或不存在，请重新读取预设库") from None
    except MiniCutError as error:
        raise HTTPException(400, str(error)) from error
    except (OSError, sqlite3.Error):
        raise HTTPException(
            500, "无法读取或保存导出设置，请检查本地项目目录后重试"
        ) from None


def export_settings_router(root: Path) -> APIRouter:
    router = APIRouter()
    library = ExportPresetLibrary(root)
    single = "/api/projects/{project_id}/highlights/{collection_id}/outputs/{output_id}/export-settings"
    batch = "/api/projects/{project_id}/highlights/{collection_id}/export-settings"

    def settings(
        project_id: str, collection_id: str, output_id: str | None = None
    ) -> ExportSettings:
        project = root / project_id
        checked(lambda: ProjectRepository(project).read())
        result = checked(lambda: read_highlights(project, collection_id))
        outputs = cast(list[dict[str, object]], result["outputs"])
        if output_id is not None and not any(
            item["output_id"] == output_id for item in outputs
        ):
            raise HTTPException(404, "作品不存在")
        return ExportSettings(project)

    @router.get(single)
    def read_single(  # pyright: ignore[reportUnusedFunction]
        project_id: SafeId, collection_id: SafeId, output_id: SafeId
    ) -> dict[str, object]:
        store = settings(project_id, collection_id, output_id)
        return checked(lambda: store.read("single", collection_id, output_id))

    @router.put(single)
    def save_single(  # pyright: ignore[reportUnusedFunction]
        project_id: SafeId, collection_id: SafeId, output_id: SafeId, body: ExportDraft
    ) -> dict[str, object]:
        store = settings(project_id, collection_id, output_id)
        if body.overrides:
            raise HTTPException(422, "单个导出不使用批量逐条覆盖")
        return checked(lambda: store.save("single", collection_id, output_id, body))

    @router.get(batch)
    def read_batch(  # pyright: ignore[reportUnusedFunction]
        project_id: SafeId, collection_id: SafeId
    ) -> dict[str, object]:
        store = settings(project_id, collection_id)
        return checked(lambda: store.read("batch", collection_id, ""))

    @router.put(batch)
    def save_batch(  # pyright: ignore[reportUnusedFunction]
        project_id: SafeId, collection_id: SafeId, body: ExportDraft
    ) -> dict[str, object]:
        store = settings(project_id, collection_id)
        return checked(lambda: store.save("batch", collection_id, "", body))

    @router.get("/api/export-presets")
    def list_presets(  # pyright: ignore[reportUnusedFunction]
    ) -> list[dict[str, object]]:
        return checked(library.list)

    @router.post("/api/export-presets", status_code=201)
    def create_preset(  # pyright: ignore[reportUnusedFunction]
        body: ExportPresetBody,
    ) -> dict[str, object]:
        return checked(lambda: library.save(body))

    @router.put("/api/export-presets/{preset_id}")
    def update_preset(  # pyright: ignore[reportUnusedFunction]
        preset_id: SafeId, body: ExportPresetBody
    ) -> dict[str, object]:
        return checked(lambda: library.save(body, preset_id))

    @router.patch("/api/export-presets/{preset_id}")
    def rename_preset(  # pyright: ignore[reportUnusedFunction]
        preset_id: SafeId, body: PresetRenameBody
    ) -> dict[str, object]:
        return checked(lambda: library.rename(preset_id, body.name))

    @router.delete("/api/export-presets/{preset_id}")
    def delete_preset(  # pyright: ignore[reportUnusedFunction]
        preset_id: SafeId,
    ) -> dict[str, bool]:
        checked(lambda: library.delete(preset_id))
        return {"deleted": True}

    return router
