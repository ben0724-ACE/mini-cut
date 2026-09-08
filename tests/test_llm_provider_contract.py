import unittest

from minicut.llm_provider import (
    TextModelProvider,
    TextModelRequest,
    TextModelResponse,
)


class FakeTextModelProvider:
    def __init__(self) -> None:
        self.requests: list[TextModelRequest] = []

    async def generate(self, request: TextModelRequest) -> TextModelResponse:
        self.requests.append(request)
        return TextModelResponse('{"summary":"ok","decisions":[]}', request.model)


async def _invoke_provider(
    provider: TextModelProvider,
    request: TextModelRequest,
) -> TextModelResponse:
    return await provider.generate(request)


class TextModelProviderContractTest(unittest.IsolatedAsyncioTestCase):
    async def test_fake_provider_can_implement_async_text_contract(self) -> None:
        provider = FakeTextModelProvider()
        request = TextModelRequest(
            model="local-model",
            system_prompt="Return JSON.",
            user_prompt="Plan these segments.",
        )

        response = await _invoke_provider(provider, request)

        self.assertEqual(provider.requests, [request])
        self.assertEqual(response.model, "local-model")
        self.assertEqual(response.content, '{"summary":"ok","decisions":[]}')

    async def test_request_and_response_reject_blank_required_fields(self) -> None:
        invalid_factories = (
            lambda: TextModelRequest("", "system", "user"),
            lambda: TextModelRequest("model", " ", "user"),
            lambda: TextModelRequest("model", "system", ""),
            lambda: TextModelResponse("", "model"),
            lambda: TextModelResponse("content", " "),
        )

        for factory in invalid_factories:
            with self.subTest(factory=factory):
                with self.assertRaisesRegex(ValueError, "blank"):
                    factory()


if __name__ == "__main__":
    unittest.main()
