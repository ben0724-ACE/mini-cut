"""Project-local editable generation drafts, separate from submitted snapshots."""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from minicut.highlight_brief import HighlightPreset


class GenerationDraft(BaseModel):
    # Drafts may be incomplete or outside generation limits while being edited.
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    preset: HighlightPreset
    custom_preset_id: str | None = Field(default=None, max_length=80)
    custom_preset_name: str | None = Field(default=None, max_length=80)
    custom_prompt: str | None = Field(default=None, max_length=25000)
    prompts: dict[HighlightPreset, Annotated[str, Field(max_length=25000)]] = Field(
        max_length=4
    )
    instructions: str = Field(max_length=12000)
    count: float
    min_seconds: float
    max_seconds: float
    limit_duration: bool = True
    hook_enabled: bool
    hook_seconds: float
    overlap_percent: float
    body_mode: Literal["continuous", "compact"]
    translation_enabled: bool
    translation_language: Literal["zh", "en"]
    subtitle_mode: Literal["bilingual", "translated"]


class GenerationSettings:
    def __init__(self, project: Path) -> None:
        self.path = project / ".minicut/generation-drafts.sqlite3"

    def read(self, asset_id: str | None = None) -> dict[str, object] | None:
        if not self.path.is_file():
            return None
        with sqlite3.connect(self.path, timeout=30) as db:
            if asset_id is None:
                row = db.execute(
                    "SELECT draft, updated_at FROM drafts ORDER BY updated_at DESC LIMIT 1"
                ).fetchone()
            else:
                row = db.execute(
                    "SELECT draft, updated_at FROM drafts WHERE asset_id=?", (asset_id,)
                ).fetchone()
        if row is None:
            return None
        return {"draft": json.loads(row[0]), "updated_at": row[1]}

    def save(self, asset_id: str, draft: GenerationDraft) -> dict[str, object]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        updated_at = datetime.now(UTC).isoformat()
        serialized = draft.model_dump_json()
        with sqlite3.connect(self.path, timeout=30) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS drafts (
                asset_id TEXT PRIMARY KEY, draft TEXT NOT NULL, updated_at TEXT NOT NULL
            )""")
            db.execute(
                "INSERT INTO drafts VALUES (?, ?, ?) ON CONFLICT(asset_id) DO UPDATE SET draft=excluded.draft, updated_at=excluded.updated_at",
                (asset_id, serialized, updated_at),
            )
        return {"draft": json.loads(serialized), "updated_at": updated_at}
