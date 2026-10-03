"""Reusable cover styles and owned backgrounds shared across local projects."""

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from minicut.cover_design import CoverDesign, CoverStyle, design_directory
from minicut.errors import UserInputError

TemplateName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)
]
ApplyMode = Literal["title", "all"]
TITLE_FIELDS = {
    "title_box",
    "font_id",
    "font_size",
    "bold",
    "text_color",
    "stroke_color",
    "stroke_width",
    "align",
}


class TemplateNotFound(UserInputError):
    pass


class TemplateNameConflict(UserInputError):
    pass


class TemplateRename(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: TemplateName


class TemplateSource(TemplateRename):
    project_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    collection_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    output_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    revision: int = Field(ge=1)
    design: CoverDesign


class CoverTemplate(BaseModel):
    template_id: str
    name: str
    style: CoverStyle
    created_at: str
    updated_at: str


class CoverTemplateLibrary:
    def __init__(self, projects_root: Path) -> None:
        self.path = projects_root / ".minicut/cover-templates.sqlite3"

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=30)
        try:
            db.execute("""CREATE TABLE IF NOT EXISTS templates (
                template_id TEXT PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                style TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )""")
            db.execute(
                "CREATE TABLE IF NOT EXISTS backgrounds (image_id TEXT PRIMARY KEY, image BLOB NOT NULL)"
            )
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _entry(row: tuple[str, str, str, str, str]) -> CoverTemplate:
        identity, name, style, created, updated = row
        return CoverTemplate(
            template_id=identity,
            name=name,
            style=CoverStyle.model_validate_json(style),
            created_at=created,
            updated_at=updated,
        )

    def list(self) -> list[CoverTemplate]:
        if not self.path.is_file():
            return []
        with self._connect() as db:
            rows = db.execute(
                "SELECT template_id,name,style,created_at,updated_at FROM templates ORDER BY name COLLATE NOCASE,template_id"
            ).fetchall()
        return [self._entry(row) for row in rows]

    def get(self, identity: str) -> CoverTemplate:
        if not self.path.is_file():
            raise TemplateNotFound("封面模板已删除或未找到")
        with self._connect() as db:
            row = db.execute(
                "SELECT template_id,name,style,created_at,updated_at FROM templates WHERE template_id=?",
                (identity,),
            ).fetchone()
        if row is None:
            raise TemplateNotFound("封面模板已删除或未找到")
        return self._entry(row)

    def background(self, image_id: str) -> bytes:
        """Copy a template-owned image into another durable local configuration."""
        with self._connect() as db:
            row = db.execute(
                "SELECT image FROM backgrounds WHERE image_id=?", (image_id,)
            ).fetchone()
        if row is None:
            raise UserInputError("模板背景不可用，请重新保存模板")
        return row[0]

    def save(
        self,
        name: str,
        design: CoverDesign,
        directory: Path,
        identity: str | None = None,
    ) -> CoverTemplate:
        if design.mode != "design":
            raise UserInputError("请先切换到自定义封面并完成设计，再保存模板")
        style = CoverStyle.model_validate(
            {
                key: value
                for key, value in design.model_dump().items()
                if key in CoverStyle.model_fields
            }
        )
        image: bytes | None = None
        if style.background_image:
            try:
                image = (directory / f"{style.background_image}.png").read_bytes()
            except OSError as error:
                raise UserInputError("背景图片不可用，请重新上传后保存模板") from error
            style.background_image = uuid4().hex
        now = datetime.now(UTC).isoformat()
        try:
            with self._connect() as db:
                if image is not None:
                    db.execute(
                        "INSERT INTO backgrounds VALUES (?,?)",
                        (style.background_image, image),
                    )
                if identity:
                    cursor = db.execute(
                        "UPDATE templates SET name=?,style=?,updated_at=? WHERE template_id=?",
                        (name, style.model_dump_json(), now, identity),
                    )
                    if cursor.rowcount == 0:
                        raise TemplateNotFound("封面模板已删除或未找到")
                else:
                    identity = f"cover-template-{uuid4().hex}"
                    db.execute(
                        "INSERT INTO templates VALUES (?,?,?,?,?)",
                        (identity, name, style.model_dump_json(), now, now),
                    )
                self._discard_unused_backgrounds(db)
        except sqlite3.IntegrityError as error:
            raise TemplateNameConflict("封面模板名称已存在，请换一个名称") from error
        return self.get(identity)

    @staticmethod
    def _discard_unused_backgrounds(db: sqlite3.Connection) -> None:
        # Applied designs own project-local copies; no export depends on this table.
        used = {
            CoverStyle.model_validate_json(row[0]).background_image
            for row in db.execute("SELECT style FROM templates")
        }
        for (image_id,) in db.execute("SELECT image_id FROM backgrounds").fetchall():
            if image_id not in used:
                db.execute("DELETE FROM backgrounds WHERE image_id=?", (image_id,))

    def rename(self, identity: str, name: str) -> CoverTemplate:
        self.get(identity)
        try:
            with self._connect() as db:
                cursor = db.execute(
                    "UPDATE templates SET name=?,updated_at=? WHERE template_id=?",
                    (name, datetime.now(UTC).isoformat(), identity),
                )
                if cursor.rowcount == 0:
                    raise TemplateNotFound("封面模板已删除或未找到")
        except sqlite3.IntegrityError as error:
            raise TemplateNameConflict("封面模板名称已存在，请换一个名称") from error
        return self.get(identity)

    def delete(self, identity: str) -> None:
        self.get(identity)
        with self._connect() as db:
            cursor = db.execute(
                "DELETE FROM templates WHERE template_id=?", (identity,)
            )
            if cursor.rowcount == 0:
                raise TemplateNotFound("封面模板已删除或未找到")
            self._discard_unused_backgrounds(db)

    def apply(
        self,
        template: CoverTemplate,
        project: Path,
        collection: str,
        output: str,
        current: CoverDesign,
        mode: ApplyMode,
    ) -> CoverDesign:
        changes = template.style.model_dump()
        if mode == "title":
            changes = {
                key: value for key, value in changes.items() if key in TITLE_FIELDS
            }
        elif template.style.background_image:
            image_id = template.style.background_image
            with self._connect() as db:
                row = db.execute(
                    "SELECT image FROM backgrounds WHERE image_id=?", (image_id,)
                ).fetchone()
            if row is None:
                raise UserInputError("模板背景不可用，请重新保存模板")
            directory = design_directory(project, collection, output)
            directory.mkdir(parents=True, exist_ok=True)
            # Each application owns its background, even after update or deletion.
            local_id = uuid4().hex
            (directory / f"{local_id}.png").write_bytes(row[0])
            changes["background_image"] = local_id
        return CoverDesign.model_validate(
            {
                **current.model_dump(),
                **changes,
                "mode": "design",
                "template_id": template.template_id,
                "template_name": template.name,
            }
        )
