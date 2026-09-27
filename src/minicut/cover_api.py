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
from minicut.cover_templates import (
    ApplyMode,
    CoverTemplateLibrary,
    TemplateNameConflict,
    TemplateNotFound,
    TemplateRename,
    TemplateSource,
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


class TemplateApplyRequest(CoverRequest):
    template_id: SafeId
    mode: ApplyMode = "all"


class BatchCoverTarget(BaseModel):
    output_id: SafeId
    revision: int = Field(ge=1)


class BatchTemplateApplyRequest(BaseModel):
    collection_id: SafeId
    template_id: SafeId
    mode: ApplyMode = "all"
    outputs: list[BatchCoverTarget] = Field(min_length=1, max_length=10)


def checked(operation: Callable[[], T]) -> T:
    try:
        return operation()
    except TemplateNotFound as error:
        raise HTTPException(404, str(error)) from error
    except TemplateNameConflict as error:
        raise HTTPException(409, str(error)) from error
    except MiniCutError as error:
        raise HTTPException(400, str(error)) from error


def cover_router(root: Path) -> APIRouter:
    router = APIRouter()
    library = CoverTemplateLibrary(root)
    route = "/api/projects/{project_id}/highlights/{collection_id}/outputs/{output_id}/cover"

    def project_path(project_id: str) -> Path:
        project = root / project_id
        checked(lambda: ProjectRepository(project).read())
        return project

    @router.get("/api/cover-templates")
    def list_templates() -> list[dict[str, object]]:  # pyright: ignore[reportUnusedFunction]
        return [item.model_dump() for item in library.list()]

    def save_template(
        body: TemplateSource, identity: str | None = None
    ) -> dict[str, object]:
        project = project_path(body.project_id)
        checked(
            lambda: validate_design(
                project, body.collection_id, body.output_id, body.revision, body.design
            )
        )
        template = checked(
            lambda: library.save(
                body.name,
                body.design,
                design_directory(project, body.collection_id, body.output_id),
                identity,
            )
        )
        return template.model_dump()

    @router.post("/api/cover-templates", status_code=201)
    def create_template(body: TemplateSource) -> dict[str, object]:  # pyright: ignore[reportUnusedFunction]
        return save_template(body)

    @router.put("/api/cover-templates/{template_id}")
    def update_template(template_id: SafeId, body: TemplateSource) -> dict[str, object]:  # pyright: ignore[reportUnusedFunction]
        return save_template(body, template_id)

    @router.patch("/api/cover-templates/{template_id}")
    def rename_template(template_id: SafeId, body: TemplateRename) -> dict[str, object]:  # pyright: ignore[reportUnusedFunction]
        return checked(lambda: library.rename(template_id, body.name)).model_dump()

    @router.delete("/api/cover-templates/{template_id}", status_code=204)
    def delete_template(template_id: SafeId) -> Response:  # pyright: ignore[reportUnusedFunction]
        checked(lambda: library.delete(template_id))
        return Response(status_code=204)

    @router.post(route + "/apply-template")
    def apply_template(  # pyright: ignore[reportUnusedFunction]
        project_id: ProjectId,
        collection_id: SafeId,
        output_id: SafeId,
        body: TemplateApplyRequest,
    ) -> dict[str, object]:  # pyright: ignore[reportUnusedFunction]
        project = project_path(project_id)
        checked(lambda: cover_context(project, collection_id, output_id, body.revision))
        template = checked(lambda: library.get(body.template_id))
        design = checked(
            lambda: library.apply(
                template, project, collection_id, output_id, body.design, body.mode
            )
        )
        checked(
            lambda: validate_design(
                project, collection_id, output_id, body.revision, design
            )
        )
        return {"design": design.model_dump()}

    @router.post("/api/projects/{project_id}/cover-template-batch")
    def apply_template_batch(  # pyright: ignore[reportUnusedFunction]
        project_id: ProjectId, body: BatchTemplateApplyRequest
    ) -> list[dict[str, object]]:  # pyright: ignore[reportUnusedFunction]
        if len({target.output_id for target in body.outputs}) != len(body.outputs):
            raise HTTPException(400, "批量封面作品不能重复")
        project = project_path(project_id)
        template = checked(lambda: library.get(body.template_id))
        results: list[dict[str, object]] = []
        for target in body.outputs:
            try:
                plan, _, _ = cover_context(
                    project, body.collection_id, target.output_id, target.revision
                )
                store = CoverStore(project, body.collection_id, target.output_id)
                saved = store.read()
                current = saved[1] if saved else CoverDesign(title=plan.title)
                design = library.apply(
                    template,
                    project,
                    body.collection_id,
                    target.output_id,
                    current,
                    body.mode,
                )
                validate_design(
                    project,
                    body.collection_id,
                    target.output_id,
                    target.revision,
                    design,
                )
                version = store.save(design, saved[0] if saved else 0)
                results.append(
                    {"output_id": target.output_id, "version": version, "error": None}
                )
            except MiniCutError as error:
                results.append(
                    {
                        "output_id": target.output_id,
                        "version": None,
                        "error": str(error),
                    }
                )
            except OSError:
                results.append(
                    {
                        "output_id": target.output_id,
                        "version": None,
                        "error": "无法保存封面，请检查项目目录",
                    }
                )
        return results

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
