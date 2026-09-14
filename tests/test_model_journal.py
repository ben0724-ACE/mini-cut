import asyncio
from pathlib import Path

import pytest

from minicut.llm_provider import ModelUsage, TextModelRequest, TextModelResponse
from minicut.model_journal import ModelJournal, RecordedProvider, estimated_cost
from minicut.transcription_task import CancellationToken, TranscriptionCancelled


def test_restart_reuses_completed_paid_request_and_changes_invalidate(
    tmp_path: Path,
) -> None:
    class Provider:
        calls = 0

        async def generate(self, request: TextModelRequest) -> TextModelResponse:
            self.calls += 1
            return TextModelResponse("{}", request.model)

    provider = Provider()

    async def run() -> None:
        request = TextModelRequest("m", "JSON", "source")
        await RecordedProvider(provider, ModelJournal(tmp_path)).generate(request)
        resumed = RecordedProvider(provider, ModelJournal(tmp_path))
        await resumed.generate(request)
        assert resumed.receipts[0]["reused"] is True
        assert provider.calls == 1
        await resumed.generate(TextModelRequest("m", "JSON", "changed"))
        assert provider.calls == 2

    asyncio.run(run())


def test_cancellation_keeps_successful_response(tmp_path: Path) -> None:
    token = CancellationToken()

    class Provider:
        async def generate(self, request: TextModelRequest) -> TextModelResponse:
            token.cancel()
            return TextModelResponse("{}", request.model)

    request = TextModelRequest("m", "JSON", "source")
    with pytest.raises(TranscriptionCancelled):
        asyncio.run(
            RecordedProvider(Provider(), ModelJournal(tmp_path), token).generate(
                request
            )
        )
    assert (
        ModelJournal(tmp_path).successful(
            __import__("json").dumps(
                __import__("dataclasses").asdict(request),
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        is not None
    )


def test_unknown_usage_is_not_zero() -> None:
    assert estimated_cost(ModelUsage()) is None
    assert (
        ModelUsage.from_dict(
            {"prompt_tokens": True, "completion_tokens": -1}
        ).to_dict()["prompt_tokens"]
        is None
    )
