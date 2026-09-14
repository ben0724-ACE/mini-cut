"""DeepSeek OpenAI-compatible HTTP adapter for LLM edit planning."""

import os
from collections.abc import Mapping
from typing import cast

import httpx

from minicut.errors import UserInputError
from minicut.llm_planner import LlmPlanner
from minicut.llm_provider import (
    ModelUsage,
    TextModelProviderError,
    TextModelRateLimitError,
    TextModelRequest,
    TextModelResponse,
)

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-v4-flash"


class DeepSeekProvider:
    """Generate JSON responses through DeepSeek's Chat Completions endpoint."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEEPSEEK_BASE_URL,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("DeepSeek API key must not be blank")
        if not base_url.strip():
            raise ValueError("DeepSeek base URL must not be blank")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._client = client

    async def generate(self, request: TextModelRequest) -> TextModelResponse:
        """Call DeepSeek without exposing credentials in request-domain objects."""
        if self._client is not None:
            return await self._generate_with_client(self._client, request)

        async with httpx.AsyncClient(
            base_url=self._base_url,
            timeout=None,
        ) as client:
            return await self._generate_with_client(client, request)

    async def _generate_with_client(
        self,
        client: httpx.AsyncClient,
        request: TextModelRequest,
    ) -> TextModelResponse:
        payload = {
            "model": request.model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
            "max_tokens": request.max_output_tokens,
            "stream": False,
        }
        try:
            response = await client.post(
                "/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=payload,
            )
        except httpx.RequestError as error:
            raise TextModelProviderError(
                "DeepSeek request could not be completed."
            ) from error

        if response.status_code == 429:
            raise TextModelRateLimitError("DeepSeek rate limit was reached.")
        if response.is_error:
            raise TextModelProviderError("DeepSeek request failed.")

        try:
            loaded: object = response.json()
            if not isinstance(loaded, dict):
                raise TypeError("response root must be an object")
            data = cast(dict[str, object], loaded)
            raw_choices = data["choices"]
            if not isinstance(raw_choices, list) or not raw_choices:
                raise TypeError("response choices must not be empty")
            choices = cast(list[object], raw_choices)
            first_choice = choices[0]
            if not isinstance(first_choice, dict):
                raise TypeError("response choice must be an object")
            choice = cast(dict[str, object], first_choice)
            usage = ModelUsage.from_dict(data.get("usage"))
            finish = choice.get("finish_reason")
            if finish is not None and finish != "stop":
                raise TextModelProviderError(
                    "DeepSeek output was truncated; increase the output budget or reduce the chapter size."
                    if finish == "length"
                    else "DeepSeek did not complete the requested JSON response.",
                    usage=usage,
                    finish_reason=str(finish),
                )
            message = choice["message"]
            if not isinstance(message, dict):
                raise TypeError("response message must be an object")
            content = cast(dict[str, object], message)["content"]
            model = data.get("model", request.model)
            if not isinstance(content, str) or not isinstance(model, str):
                raise TypeError("response content or model has an invalid type")
            return TextModelResponse(
                content=content,
                model=model,
                usage=usage,
                finish_reason=cast(str | None, finish),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise TextModelProviderError(
                "DeepSeek returned an invalid response."
            ) from error


def create_deepseek_planner_from_env(
    environ: Mapping[str, str] | None = None,
    *,
    timeout_seconds: float = 60.0,
) -> LlmPlanner:
    """Create a Flash planner from environment variables without persisting secrets."""
    values = os.environ if environ is None else environ
    api_key = values.get("DEEPSEEK_API_KEY", "")
    if not api_key.strip():
        raise UserInputError("DEEPSEEK_API_KEY is required for DeepSeek planning.")
    model = values.get("DEEPSEEK_MODEL", DEEPSEEK_MODEL)
    base_url = values.get("DEEPSEEK_BASE_URL", DEEPSEEK_BASE_URL)
    provider = DeepSeekProvider(api_key, base_url=base_url)
    return LlmPlanner(
        provider,
        model,
        timeout_seconds=timeout_seconds,
    )


__all__ = [
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_MODEL",
    "DeepSeekProvider",
    "create_deepseek_planner_from_env",
]
