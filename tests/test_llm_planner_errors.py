import asyncio
import unittest

from minicut.edit_plan import EditBrief, EditIntensity
from minicut.llm_planner import (
    LlmPlanner,
    ModelProviderError,
    ModelRateLimitError,
    ModelTimeoutError,
)
from minicut.llm_provider import (
    TextModelRateLimitError,
    TextModelRequest,
    TextModelResponse,
)
from minicut.semantic_segment import SegmentLabel, SemanticSegment


def _brief() -> EditBrief:
    return EditBrief(1_000, EditIntensity.BALANCED, "natural")


def _segments() -> tuple[SemanticSegment, ...]:
    return (
        SemanticSegment(
            "segment-1",
            "内容",
            0,
            800,
            ("utterance-1",),
            ("word-1",),
            labels=(SegmentLabel.CONTENT,),
        ),
    )


class NeverCompletesProvider:
    def __init__(self) -> None:
        self.cancelled = False

    async def generate(self, request: TextModelRequest) -> TextModelResponse:
        del request
        try:
            await asyncio.Event().wait()
        finally:
            self.cancelled = True
        raise AssertionError("unreachable")


class FailingProvider:
    def __init__(self, error: BaseException) -> None:
        self.error = error

    async def generate(self, request: TextModelRequest) -> TextModelResponse:
        del request
        raise self.error


class LlmPlannerErrorTest(unittest.IsolatedAsyncioTestCase):
    async def test_timeout_cancels_provider_and_returns_safe_error(self) -> None:
        provider = NeverCompletesProvider()
        planner = LlmPlanner(provider, "model", timeout_seconds=0.001)

        with self.assertRaisesRegex(ModelTimeoutError, "timed out"):
            await planner.plan(_brief(), _segments())

        self.assertTrue(provider.cancelled)

    async def test_rate_limit_is_mapped_without_provider_details(self) -> None:
        planner = LlmPlanner(
            FailingProvider(TextModelRateLimitError("quota for sk-secret")),
            "model",
        )

        with self.assertRaises(ModelRateLimitError) as raised:
            await planner.plan(_brief(), _segments())

        self.assertNotIn("sk-secret", str(raised.exception))

    async def test_user_cancellation_propagates_unchanged(self) -> None:
        planner = LlmPlanner(FailingProvider(asyncio.CancelledError()), "model")

        with self.assertRaises(asyncio.CancelledError):
            await planner.plan(_brief(), _segments())

    async def test_unexpected_provider_failure_is_safely_mapped(self) -> None:
        planner = LlmPlanner(FailingProvider(RuntimeError("private response")), "model")

        with self.assertRaises(ModelProviderError) as raised:
            await planner.plan(_brief(), _segments())

        self.assertNotIn("private response", str(raised.exception))

    def test_timeout_must_be_positive(self) -> None:
        with self.assertRaisesRegex(ValueError, "timeout"):
            LlmPlanner(FailingProvider(RuntimeError()), "model", timeout_seconds=0)


if __name__ == "__main__":
    unittest.main()
