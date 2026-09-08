import json
import unittest
from collections.abc import Mapping
from typing import cast

import httpx

from minicut.deepseek_provider import (
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    DeepSeekProvider,
    create_deepseek_planner_from_env,
)
from minicut.errors import UserInputError
from minicut.llm_provider import (
    TextModelProviderError,
    TextModelRateLimitError,
    TextModelRequest,
)


def _request() -> TextModelRequest:
    return TextModelRequest("deepseek-v4-flash", "Return JSON.", "Plan input.")


def _status_transport(status_code: int) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(status_code, text="private provider details")

    return httpx.MockTransport(handle)


class DeepSeekProviderTest(unittest.IsolatedAsyncioTestCase):
    async def test_openai_compatible_json_request_is_mapped_to_response(self) -> None:
        captured: dict[str, object] = {}

        def handle(request: httpx.Request) -> httpx.Response:
            captured["authorization"] = request.headers["Authorization"]
            captured["payload"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "model": "DeepSeek-V4-Flash-0731",
                    "choices": [{"message": {"content": '{"summary":"ok"}'}}],
                },
            )

        async with httpx.AsyncClient(
            base_url=DEEPSEEK_BASE_URL,
            transport=httpx.MockTransport(handle),
        ) as client:
            provider = DeepSeekProvider("test-token", client=client)
            response = await provider.generate(_request())

        payload = cast(Mapping[str, object], captured["payload"])
        self.assertEqual(captured["authorization"], "Bearer test-token")
        self.assertEqual(payload["model"], DEEPSEEK_MODEL)
        self.assertEqual(
            payload["messages"],
            [
                {"role": "system", "content": "Return JSON."},
                {"role": "user", "content": "Plan input."},
            ],
        )
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertIs(payload["stream"], False)
        self.assertEqual(response.content, '{"summary":"ok"}')
        self.assertEqual(response.model, "DeepSeek-V4-Flash-0731")

    async def test_rate_limit_and_other_http_failures_are_safely_mapped(self) -> None:
        cases = (
            (429, TextModelRateLimitError),
            (500, TextModelProviderError),
        )

        for status_code, expected_error in cases:
            with self.subTest(status_code=status_code):
                async with httpx.AsyncClient(
                    base_url=DEEPSEEK_BASE_URL,
                    transport=_status_transport(status_code),
                ) as client:
                    provider = DeepSeekProvider("test-token", client=client)
                    with self.assertRaises(expected_error) as raised:
                        await provider.generate(_request())
                self.assertNotIn("private provider details", str(raised.exception))
                self.assertNotIn("test-token", str(raised.exception))

    async def test_malformed_success_response_is_safely_rejected(self) -> None:
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json={"choices": []})
        )
        async with httpx.AsyncClient(
            base_url=DEEPSEEK_BASE_URL,
            transport=transport,
        ) as client:
            provider = DeepSeekProvider("test-token", client=client)
            with self.assertRaises(TextModelProviderError):
                await provider.generate(_request())

    def test_environment_factory_requires_key_and_defaults_to_flash(self) -> None:
        with self.assertRaisesRegex(UserInputError, "DEEPSEEK_API_KEY"):
            create_deepseek_planner_from_env({})

        planner = create_deepseek_planner_from_env({"DEEPSEEK_API_KEY": "test-token"})
        self.assertEqual(planner.model, DEEPSEEK_MODEL)


if __name__ == "__main__":
    unittest.main()
