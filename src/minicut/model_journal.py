"""Project-local model receipts and resumable successful requests, using SQLite."""

import json
import math
import os
import sqlite3
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from minicut.llm_provider import (
    ModelUsage,
    TextModelProvider,
    TextModelProviderError,
    TextModelRequest,
    TextModelResponse,
)
from minicut.transcription_task import CancellationToken


class ModelJournal:
    def __init__(self, project: Path) -> None:
        path = project / ".minicut" / "model-requests.sqlite3"
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS requests (
                id INTEGER PRIMARY KEY, request TEXT NOT NULL, status TEXT NOT NULL,
                response TEXT, receipt TEXT NOT NULL)""")

    def connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=30)

    def successful(
        self, request: str
    ) -> tuple[TextModelResponse, dict[str, object]] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT response, receipt FROM requests WHERE request=? AND status='succeeded' ORDER BY id DESC LIMIT 1",
                (request,),
            ).fetchone()
        if row is None:
            return None
        data = json.loads(row[0])
        return TextModelResponse(
            data["content"],
            data["model"],
            ModelUsage.from_dict(data.get("usage")),
            data.get("finish_reason"),
        ), json.loads(row[1])


def estimated_cost(usage: ModelUsage) -> float | None:
    """Configured USD per million tokens; absent prices/metrics remain unknown."""
    fields = ("HIT", "MISS", "OUTPUT")
    counts = (
        usage.prompt_cache_hit_tokens,
        usage.prompt_cache_miss_tokens,
        usage.completion_tokens,
    )
    try:
        rates = [
            float(os.environ[f"MINICUT_PRICE_{key}_USD_PER_MILLION"]) for key in fields
        ]
        if any(rate < 0 or not math.isfinite(rate) for rate in rates) or any(
            count is None for count in counts
        ):
            return None
        return (
            sum(
                rate * cast(int, count)
                for rate, count in zip(rates, counts, strict=True)
            )
            / 1_000_000
        )
    except (KeyError, ValueError):
        return None


class RecordedProvider:
    def __init__(
        self,
        provider: TextModelProvider,
        journal: ModelJournal,
        cancellation: CancellationToken | None = None,
    ) -> None:
        self.provider = provider
        self.journal = journal
        self.cancellation = cancellation or CancellationToken()
        self.receipts: list[dict[str, object]] = []

    async def generate(self, request: TextModelRequest) -> TextModelResponse:
        self.cancellation.raise_if_cancelled()
        serialized = json.dumps(asdict(request), ensure_ascii=False, sort_keys=True)
        cached = self.journal.successful(serialized)
        if cached is not None:
            response, receipt = cached
            self.receipts.append({**receipt, "reused": True, "estimated_cost_usd": 0.0})
            return response
        receipt: dict[str, object] = {
            "model": request.model,
            "requested_at": datetime.now(UTC).isoformat(),
            "reused": False,
            "usage": ModelUsage().to_dict(),
            "estimated_cost_usd": None,
            "price_source": os.environ.get("MINICUT_PRICE_SOURCE"),
            "price_date": os.environ.get("MINICUT_PRICE_DATE"),
            "output_budget": request.max_output_tokens,
        }
        with self.journal.connect() as db:
            cursor = db.execute(
                "INSERT INTO requests(request,status,receipt) VALUES (?,'running',?)",
                (serialized, json.dumps(receipt)),
            )
            identity = cursor.lastrowid
        try:
            response = await self.provider.generate(request)
            receipt.update(
                usage=response.usage.to_dict(),
                finish_reason=response.finish_reason,
                estimated_cost_usd=estimated_cost(response.usage),
                model=response.model,
            )
            with self.journal.connect() as db:
                db.execute(
                    "UPDATE requests SET status='succeeded', response=?, receipt=? WHERE id=?",
                    (
                        json.dumps(asdict(response), ensure_ascii=False),
                        json.dumps(receipt),
                        identity,
                    ),
                )
            self.receipts.append(receipt)
            # Persist the successful paid result before acknowledging cancellation.
            self.cancellation.raise_if_cancelled()
            return response
        except BaseException as error:
            if isinstance(error, TextModelProviderError):
                receipt.update(
                    usage=error.usage.to_dict(),
                    finish_reason=error.finish_reason,
                    estimated_cost_usd=estimated_cost(error.usage),
                )
            with self.journal.connect() as db:
                db.execute(
                    "UPDATE requests SET status='failed', receipt=? WHERE id=? AND status='running'",
                    (json.dumps(receipt), identity),
                )
            if not self.receipts or self.receipts[-1] is not receipt:
                self.receipts.append(receipt)
            raise
