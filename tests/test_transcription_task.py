import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from minicut.transcript import Transcript, TranscriptSource
from minicut.transcription_cache import (
    TranscriptCacheRepository,
    TranscriptionCacheKey,
)
from minicut.transcription_task import (
    CancellationToken,
    TranscriptionCancelled,
    TranscriptionPhase,
    TranscriptionProgressEvent,
    run_transcription_task,
)


def _key() -> TranscriptionCacheKey:
    return TranscriptionCacheKey(
        media_fingerprint="sha256:media-a",
        provider="mlx-whisper",
        model="small",
        language="zh",
        initial_prompt=None,
    )


def _transcript() -> Transcript:
    return Transcript(
        transcript_id="transcript-1",
        source=TranscriptSource(
            asset_id="asset-1",
            provider="mlx-whisper",
            model="small",
        ),
        language="zh",
    )


class TranscriptionTaskTest(unittest.TestCase):
    def test_cache_miss_reports_progress_and_persists_the_result(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            repository = TranscriptCacheRepository(
                Path(temporary_directory) / "transcript-cache.json"
            )
            phases: list[TranscriptionPhase] = []
            producer_calls = 0

            def producer(token: CancellationToken) -> Transcript:
                nonlocal producer_calls
                producer_calls += 1
                self.assertFalse(token.is_cancelled)
                return _transcript()

            result = run_transcription_task(
                repository,
                _key(),
                producer,
                on_progress=lambda event: phases.append(event.phase),
            )

            self.assertEqual(repository.read(_key()), result)

        self.assertEqual(producer_calls, 1)
        self.assertEqual(
            phases,
            [
                TranscriptionPhase.CACHE_LOOKUP,
                TranscriptionPhase.TRANSCRIBING,
                TranscriptionPhase.PERSISTING,
                TranscriptionPhase.COMPLETED,
            ],
        )

    def test_cache_hit_reports_hit_and_skips_the_producer(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            repository = TranscriptCacheRepository(
                Path(temporary_directory) / "transcript-cache.json"
            )
            repository.write(_key(), _transcript())
            phases: list[TranscriptionPhase] = []

            def unexpected_producer(token: CancellationToken) -> Transcript:
                del token
                self.fail("producer must not run for a cache hit")

            result = run_transcription_task(
                repository,
                _key(),
                unexpected_producer,
                on_progress=lambda event: phases.append(event.phase),
            )

        self.assertEqual(result, _transcript())
        self.assertEqual(
            phases,
            [
                TranscriptionPhase.CACHE_LOOKUP,
                TranscriptionPhase.CACHE_HIT,
                TranscriptionPhase.COMPLETED,
            ],
        )

    def test_cancellation_before_inference_skips_producer_and_cache(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            repository = TranscriptCacheRepository(
                Path(temporary_directory) / "transcript-cache.json"
            )
            token = CancellationToken()
            phases: list[TranscriptionPhase] = []
            producer_calls = 0

            def producer(cancellation: CancellationToken) -> Transcript:
                nonlocal producer_calls
                producer_calls += 1
                return _transcript()

            def report_progress(event: TranscriptionProgressEvent) -> None:
                phase = event.phase
                phases.append(phase)
                if phase is TranscriptionPhase.TRANSCRIBING:
                    token.cancel()

            with self.assertRaisesRegex(TranscriptionCancelled, "cancelled"):
                run_transcription_task(
                    repository,
                    _key(),
                    producer,
                    cancellation=token,
                    on_progress=report_progress,
                )

            self.assertIsNone(repository.read(_key()))

        self.assertEqual(producer_calls, 0)
        self.assertEqual(
            phases,
            [
                TranscriptionPhase.CACHE_LOOKUP,
                TranscriptionPhase.TRANSCRIBING,
                TranscriptionPhase.CANCELLED,
            ],
        )

    def test_cancellation_after_inference_does_not_publish_result(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            repository = TranscriptCacheRepository(
                Path(temporary_directory) / "transcript-cache.json"
            )
            token = CancellationToken()
            phases: list[TranscriptionPhase] = []

            def producer(cancellation: CancellationToken) -> Transcript:
                self.assertIs(cancellation, token)
                cancellation.cancel()
                return _transcript()

            with self.assertRaisesRegex(TranscriptionCancelled, "cancelled"):
                run_transcription_task(
                    repository,
                    _key(),
                    producer,
                    cancellation=token,
                    on_progress=lambda event: phases.append(event.phase),
                )

            self.assertIsNone(repository.read(_key()))

        self.assertEqual(
            phases,
            [
                TranscriptionPhase.CACHE_LOOKUP,
                TranscriptionPhase.TRANSCRIBING,
                TranscriptionPhase.CANCELLED,
            ],
        )


if __name__ == "__main__":
    unittest.main()
