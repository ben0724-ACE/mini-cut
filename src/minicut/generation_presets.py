"""Reusable generation workflows shared by projects in one local workspace."""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Self
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

from minicut.generation_settings import GenerationDraft
from minicut.highlight_brief import HighlightBrief, HighlightPreset

PresetName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)
]


class PresetRenameBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: PresetName


class GenerationPresetBody(PresetRenameBody):
    draft: GenerationDraft

    @model_validator(mode="after")
    def reusable_configuration(self) -> Self:
        draft = self.draft
        if not draft.count.is_integer() or not 1 <= draft.count <= 10:
            raise ValueError("数量需为 1–10 的整数")
        prompt = self.active_prompt()
        if not prompt.strip():
            raise ValueError("保存预设前请填写预设提示词")
        # Validate active settings; disabled controls retain their draft values.
        limited = (
            draft.limit_duration and draft.preset is not HighlightPreset.CLEAN_SPEECH
        )
        HighlightBrief(
            preset=draft.preset,
            count=int(draft.count),
            min_ms=round(draft.min_seconds * 1000) if limited else None,
            max_ms=round(draft.max_seconds * 1000) if limited else None,
            hook_ms=round(draft.hook_seconds * 1000) if draft.hook_enabled else None,
            instructions=draft.instructions,
            preset_prompt=prompt,
            max_source_overlap=1 if draft.count == 1 else draft.overlap_percent / 100,
            body_mode=draft.body_mode,
            translation_language=(
                draft.translation_language if draft.translation_enabled else None
            ),
            subtitle_mode=draft.subtitle_mode,
        )
        return self

    def active_prompt(self) -> str:
        if self.draft.custom_preset_id and self.draft.custom_prompt is not None:
            return self.draft.custom_prompt
        return self.draft.prompts.get(self.draft.preset, "")

    def template_json(self) -> str:
        # Save the active prompt, not unrelated per-preset drafts or template links.
        template = self.draft.model_copy(
            update={
                "prompts": {self.draft.preset: self.active_prompt()},
                "custom_preset_id": None,
                "custom_preset_name": None,
                "custom_prompt": None,
            }
        )
        return template.model_dump_json()


class PresetNotFound(Exception):
    pass


class PresetNameConflict(Exception):
    pass


class GenerationPresetLibrary:
    def __init__(self, projects_root: Path) -> None:
        self.path = projects_root / ".minicut/generation-presets.sqlite3"

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=30)
        db.execute("""CREATE TABLE IF NOT EXISTS presets (
            preset_id TEXT PRIMARY KEY,
            name TEXT NOT NULL COLLATE NOCASE UNIQUE,
            draft TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""")
        return db

    @staticmethod
    def _entry(row: tuple[str, str, str, str, str]) -> dict[str, object]:
        identity, name, draft, created, updated = row
        return {
            "preset_id": identity,
            "name": name,
            "draft": json.loads(draft),
            "created_at": created,
            "updated_at": updated,
        }

    def list(self) -> list[dict[str, object]]:
        if not self.path.is_file():
            return []
        with self._connect() as db:
            rows = db.execute(
                "SELECT preset_id,name,draft,created_at,updated_at FROM presets ORDER BY name COLLATE NOCASE,preset_id"
            ).fetchall()
        return [self._entry(row) for row in rows]

    def create(self, body: GenerationPresetBody) -> dict[str, object]:
        identity = f"preset-{uuid4().hex}"
        now = datetime.now(UTC).isoformat()
        row = (identity, body.name, body.template_json(), now, now)
        try:
            with self._connect() as db:
                db.execute("INSERT INTO presets VALUES (?,?,?,?,?)", row)
        except sqlite3.IntegrityError as error:
            raise PresetNameConflict from error
        return self._entry(row)

    def update(self, identity: str, body: GenerationPresetBody) -> dict[str, object]:
        return self._update(identity, body.name, body.template_json())

    def rename(self, identity: str, name: str) -> dict[str, object]:
        return self._update(identity, name)

    def _update(
        self, identity: str, name: str, draft: str | None = None
    ) -> dict[str, object]:
        if not self.path.is_file():
            raise PresetNotFound
        try:
            with self._connect() as db:
                now = datetime.now(UTC).isoformat()
                if draft is None:
                    cursor = db.execute(
                        "UPDATE presets SET name=?,updated_at=? WHERE preset_id=?",
                        (name, now, identity),
                    )
                else:
                    cursor = db.execute(
                        "UPDATE presets SET name=?,draft=?,updated_at=? WHERE preset_id=?",
                        (name, draft, now, identity),
                    )
                if cursor.rowcount == 0:
                    raise PresetNotFound
                row = db.execute(
                    "SELECT preset_id,name,draft,created_at,updated_at FROM presets WHERE preset_id=?",
                    (identity,),
                ).fetchone()
        except sqlite3.IntegrityError as error:
            raise PresetNameConflict from error
        return self._entry(row)

    def delete(self, identity: str) -> None:
        if not self.path.is_file():
            raise PresetNotFound
        with self._connect() as db:
            if (
                db.execute(
                    "DELETE FROM presets WHERE preset_id=?", (identity,)
                ).rowcount
                == 0
            ):
                raise PresetNotFound
