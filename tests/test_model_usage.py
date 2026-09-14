import asyncio
import json

import httpx
import pytest

from minicut.deepseek_provider import DeepSeekProvider
from minicut.llm_provider import TextModelProviderError, TextModelRequest


def test_usage_and_output_budget_and_truncation() -> None:
    async def run() -> None:
        def handle(request: httpx.Request) -> httpx.Response:
            assert json.loads(request.content)["max_tokens"] == 512
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"finish_reason": "length", "message": {"content": "{}"}}
                    ],
                    "usage": {
                        "prompt_tokens": 100,
                        "completion_tokens": 512,
                        "prompt_cache_hit_tokens": 64,
                        "prompt_cache_miss_tokens": 36,
                    },
                },
            )

        async with httpx.AsyncClient(
            base_url="https://example.test", transport=httpx.MockTransport(handle)
        ) as client:
            with pytest.raises(TextModelProviderError, match="truncated") as error:
                await DeepSeekProvider("test", client=client).generate(
                    TextModelRequest("test", "JSON", "data", max_output_tokens=512)
                )
            assert error.value.usage.prompt_cache_hit_tokens == 64

    asyncio.run(run())


def test_unknown_usage_and_success() -> None:
    async def run() -> None:
        async with httpx.AsyncClient(
            base_url="https://example.test",
            transport=httpx.MockTransport(
                lambda r: httpx.Response(
                    200,
                    json={
                        "choices": [
                            {"finish_reason": "stop", "message": {"content": "{}"}}
                        ]
                    },
                )
            ),
        ) as client:
            result = await DeepSeekProvider("test", client=client).generate(
                TextModelRequest("m", "JSON", "data")
            )
            assert result.usage.prompt_tokens is None
            assert result.finish_reason == "stop"

    asyncio.run(run())
