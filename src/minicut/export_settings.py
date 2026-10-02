"""Remember editable export settings separately from completed export snapshots."""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal, Self
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from minicut.generation_presets import (
    PresetNameConflict,
    PresetNotFound,
    PresetRenameBody,
)
from minicut.render_profile import RenderProfile

SafeId = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")]


class ExportGeometry(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    aspect_ratio: Literal["original", "16:9", "9:16", "1:1", "4:5"] = "original"
    resolution: Literal[720, 1080] = 1080
    fit: Literal["pad", "crop"] = "pad"
    crop_left: float = Field(default=0, ge=0, le=95)
    crop_right: float = Field(default=0, ge=0, le=95)
    crop_top: float = Field(default=0, ge=0, le=95)
    crop_bottom: float = Field(default=0, ge=0, le=95)

    @model_validator(mode="after")
    def validate_geometry(self) -> Self:
        RenderProfile(**self.model_dump(include=set(ExportGeometry.model_fields)))
        return self


class ExportOptions(ExportGeometry):
    subtitle_mode: Literal["soft", "burned"] = "soft"
    audio_fade_ms: int = Field(default=0, ge=0, le=500, strict=True)
    denoiser_id: Literal["none", "afftdn"] = "none"


class ExportDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    options: ExportOptions = Field(default_factory=ExportOptions)
    overrides: dict[SafeId, ExportGeometry] = Field(
        default_factory=dict, max_length=100
    )
    preset_id: SafeId | None = None
    preset_name: str | None = Field(default=None, max_length=80)


class ExportSettings:
    def __init__(self, project: Path) -> None:
        self.path = project / ".minicut/export-settings.sqlite3"

    def read(self, mode: str, collection: str, output: str) -> dict[str, object]:
        if self.path.is_file():
            with sqlite3.connect(self.path, timeout=30) as db:
                row = db.execute(
                    "SELECT draft,updated_at FROM drafts WHERE mode=? AND collection_id=? AND output_id=?",
                    (mode, collection, output),
                ).fetchone()
                source = "saved"
                if row is None:
                    row = db.execute(
                        "SELECT draft,updated_at FROM drafts WHERE mode=? ORDER BY updated_at DESC LIMIT 1",
                        (mode,),
                    ).fetchone()
                    source = "project"
            if row:
                draft = json.loads(row[0])
                if source == "project":
                    draft["overrides"] = {}
                return {"source": source, "draft": draft, "updated_at": row[1]}
        return {"source": "default", "draft": ExportDraft().model_dump(mode="json")}

    def save(
        self, mode: str, collection: str, output: str, draft: ExportDraft
    ) -> dict[str, object]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        now = datetime.now(UTC).isoformat()
        with sqlite3.connect(self.path, timeout=30) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS drafts (
                mode TEXT NOT NULL, collection_id TEXT NOT NULL, output_id TEXT NOT NULL,
                draft TEXT NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY (mode,collection_id,output_id)
            )""")
            db.execute(
                "INSERT INTO drafts VALUES (?,?,?,?,?) ON CONFLICT(mode,collection_id,output_id) DO UPDATE SET draft=excluded.draft,updated_at=excluded.updated_at",
                (mode, collection, output, draft.model_dump_json(), now),
            )
        return {
            "source": "saved",
            "draft": draft.model_dump(mode="json"),
            "updated_at": now,
        }


class ExportPresetBody(PresetRenameBody):
    options: ExportOptions


class ExportPresetLibrary:
    def __init__(self, root: Path) -> None:
        self.path = root / ".minicut/export-presets.sqlite3"

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=30)
        db.execute("""CREATE TABLE IF NOT EXISTS presets (
            preset_id TEXT PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE UNIQUE,
            options TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""")
        return db

    @staticmethod
    def _entry(row: tuple[str, str, str, str, str]) -> dict[str, object]:
        return dict(
            preset_id=row[0],
            name=row[1],
            options=json.loads(row[2]),
            created_at=row[3],
            updated_at=row[4],
        )

    def list(self) -> list[dict[str, object]]:
        if not self.path.is_file():
            return []
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM presets ORDER BY name COLLATE NOCASE,preset_id"
            ).fetchall()
        return [self._entry(row) for row in rows]

    def save(
        self, body: ExportPresetBody, identity: str | None = None
    ) -> dict[str, object]:
        now = datetime.now(UTC).isoformat()
        try:
            with self._connect() as db:
                if identity is None:
                    identity = f"export-{uuid4().hex}"
                    db.execute(
                        "INSERT INTO presets VALUES (?,?,?,?,?)",
                        (identity, body.name, body.options.model_dump_json(), now, now),
                    )
                elif (
                    db.execute(
                        "UPDATE presets SET name=?,options=?,updated_at=? WHERE preset_id=?",
                        (body.name, body.options.model_dump_json(), now, identity),
                    ).rowcount
                    == 0
                ):
                    raise PresetNotFound
                row = db.execute(
                    "SELECT * FROM presets WHERE preset_id=?", (identity,)
                ).fetchone()
        except sqlite3.IntegrityError as error:
            raise PresetNameConflict from error
        return self._entry(row)

    def rename(self, identity: str, name: str) -> dict[str, object]:
        try:
            with self._connect() as db:
                if (
                    db.execute(
                        "UPDATE presets SET name=?,updated_at=? WHERE preset_id=?",
                        (name, datetime.now(UTC).isoformat(), identity),
                    ).rowcount
                    == 0
                ):
                    raise PresetNotFound
                row = db.execute(
                    "SELECT * FROM presets WHERE preset_id=?", (identity,)
                ).fetchone()
        except sqlite3.IntegrityError as error:
            raise PresetNameConflict from error
        return self._entry(row)

    def delete(self, identity: str) -> None:
        with self._connect() as db:
            if (
                db.execute(
                    "DELETE FROM presets WHERE preset_id=?", (identity,)
                ).rowcount
                == 0
            ):
                raise PresetNotFound
