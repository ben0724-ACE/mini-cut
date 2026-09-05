import json
import unittest
from io import StringIO
from typing import cast

from minicut.log import LogContext, create_logger, log_event, new_job_id, new_request_id


class StructuredLogTest(unittest.TestCase):
    def test_event_is_json_and_includes_request_and_job_context(self) -> None:
        stream = StringIO()
        logger = create_logger(
            LogContext(request_id="request-1", job_id="job-1"),
            stream=stream,
        )

        log_event(logger, "transcription.started", "Transcription started.")

        payload = cast(dict[str, object], json.loads(stream.getvalue()))
        self.assertEqual(payload["level"], "INFO")
        self.assertEqual(payload["event"], "transcription.started")
        self.assertEqual(payload["message"], "Transcription started.")
        self.assertEqual(payload["request_id"], "request-1")
        self.assertEqual(payload["job_id"], "job-1")

    def test_request_and_job_ids_are_generated_independently(self) -> None:
        request_id = new_request_id()
        job_id = new_job_id()

        self.assertTrue(request_id)
        self.assertTrue(job_id)
        self.assertNotEqual(request_id, job_id)

    def test_sensitive_structured_fields_are_redacted(self) -> None:
        stream = StringIO()
        logger = create_logger(LogContext(request_id="request-1"), stream=stream)

        log_event(
            logger,
            "planner.requested",
            "Planning requested.",
            fields={
                "api_key": "secret-api-key",
                "headers": {
                    "Authorization": "Bearer secret-token",
                    "Content-Type": "application/json",
                },
                "prompt": "the complete private prompt",
                "model": "example-model",
            },
        )

        serialized = stream.getvalue()
        payload = cast(dict[str, object], json.loads(serialized))
        fields = cast(dict[str, object], payload["fields"])
        headers = cast(dict[str, object], fields["headers"])

        self.assertEqual(fields["api_key"], "[REDACTED]")
        self.assertEqual(headers["Authorization"], "[REDACTED]")
        self.assertEqual(fields["prompt"], "[REDACTED]")
        self.assertEqual(fields["model"], "example-model")
        self.assertNotIn("secret", serialized)
        self.assertNotIn("complete private prompt", serialized)


if __name__ == "__main__":
    unittest.main()
