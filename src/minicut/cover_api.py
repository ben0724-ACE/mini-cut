"""Cover editor endpoints; all media and fonts remain on the local machine."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Literal, TypeVar
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from minicut.cover_design import (
    CoverDesign,
    CoverStore,
    cover_context,
    cover_fonts,
    design_directory,
    normalize_background,
    render_cover,
    validate_design,
)
from minicut.errors import MiniCutError
from minicut.project import ProjectRepository

SafeId = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")]
ProjectId = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")]
T = TypeVar("T")


class CoverRequest(BaseModel):
    revision: int = Field(ge=1)
    design: CoverDesign


class CoverSaveRequest(CoverRequest):
    base_version: int = Field(ge=0)


def checked(operation: Callable[[], T]) -> T:
    try:
        return operation()
    except MiniCutError as error:
        raise HTTPException(400, str(error)) from error


def cover_router(root: Path) -> APIRouter:
    router = APIRouter()
    route = "/api/projects/{project_id}/highlights/{collection_id}/outputs/{output_id}/cover"

    def project_path(project_id: str) -> Path:
        project = root / project_id
        checked(lambda: ProjectRepository(project).read())
        return project

    @router.get(route)
    def read(  # pyright: ignore[reportUnusedFunction]
        project_id: ProjectId,
        collection_id: SafeId,
        output_id: SafeId,
        revision: int = 1,
    ) -> dict[str, object]:
        project = project_path(project_id)
        plan, _, _ = checked(
            lambda: cover_context(project, collection_id, output_id, revision)
        )
        saved = CoverStore(project, collection_id, output_id).read()
        return {
            "version": saved[0] if saved else 0,
            "design": (
                saved[1] if saved else CoverDesign(title=plan.title)
            ).model_dump(),
            "fonts": [
                {"id": key, "name": value[0]} for key, value in cover_fonts().items()
            ],
        }

    @router.put(route)
    def save(  # pyright: ignore[reportUnusedFunction]
        project_id: ProjectId,
        collection_id: SafeId,
        output_id: SafeId,
        body: CoverSaveRequest,
    ) -> dict[str, object]:
        project = project_path(project_id)
        checked(
            lambda: validate_design(
                project, collection_id, output_id, body.revision, body.design
            )
        )
        version = checked(
            lambda: CoverStore(project, collection_id, output_id).save(
                body.design, body.base_version
            )
        )
        return {"version": version, "design": body.design.model_dump()}

    @router.post(route + "/preview")
    def preview(  # pyright: ignore[reportUnusedFunction]
        project_id: ProjectId,
        collection_id: SafeId,
        output_id: SafeId,
        body: CoverRequest,
    ) -> Response:
        project = project_path(project_id)
        data, warnings = checked(
            lambda: render_cover(
                project, collection_id, output_id, body.revision, body.design
            )
        )
        return Response(
            data,
            media_type="image/png",
            headers={
                "X-Cover-Warnings": json.dumps(warnings, ensure_ascii=True),
                "Cache-Control": "no-store",
            },
        )

    @router.get(route + "/download")
    def download(  # pyright: ignore[reportUnusedFunction]
        project_id: ProjectId,
        collection_id: SafeId,
        output_id: SafeId,
        revision: int,
        version: int,
        format: Literal["png", "jpg"] = "png",
    ) -> Response:
        project = project_path(project_id)
        saved = CoverStore(project, collection_id, output_id).read(version)
        if not saved or saved[1].mode != "design":
            raise HTTPException(
                400, "请先保存自定义封面；成片第一帧请从视频导出结果下载"
            )
        data, _ = checked(
            lambda: render_cover(
                project, collection_id, output_id, revision, saved[1], format
            )
        )
        return Response(
            data,
            media_type="image/jpeg" if format == "jpg" else "image/png",
            headers={
                "Content-Disposition": f'attachment; filename="{output_id}-cover-v{version}.{format}"'
            },
        )

    @router.post(route + "/background")
    async def upload(  # pyright: ignore[reportUnusedFunction]
        project_id: ProjectId,
        collection_id: SafeId,
        output_id: SafeId,
        request: Request,
        revision: int = 1,
    ) -> dict[str, str]:
        project = project_path(project_id)
        checked(lambda: cover_context(project, collection_id, output_id, revision))
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 15 * 1024 * 1024:
                raise HTTPException(413, "背景图片不能超过 15 MB")
        normalized = await run_in_threadpool(
            checked, lambda: normalize_background(bytes(data))
        )
        identity = uuid4().hex
        directory = design_directory(project, collection_id, output_id)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{identity}.png").write_bytes(normalized)
        return {"image_id": identity}

    return router
