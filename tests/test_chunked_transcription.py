from dataclasses import replace
from pathlib import Path

import pytest

from minicut.chunked_transcription import transcribe_chunks
from minicut.media import MediaAsset
from minicut.transcript import Transcript, TranscriptSource, Word
from minicut.transcription_cache import TranscriptionCacheKey
from minicut.transcription_task import CancellationToken, TranscriptionCancelled


def test_resume_absolute_offsets_and_last_chunk(tmp_path: Path) -> None:
    asset = MediaAsset(
        asset_id="a",
        source_path="/source.wav",
        duration_ms=25000,
        content_fingerprint="fingerprint",
        streams=(),
    )
    key = TranscriptionCacheKey("fingerprint", "mlx", "test", "en", None)
    calls: list[int] = []
    token = CancellationToken()

    def produce(chunk: MediaAsset) -> Transcript:
        calls.append(chunk.duration_ms)
        return Transcript(
            "t",
            TranscriptSource("a", "mlx", "test"),
            "en",
            (Word("w", "word", 2500, 3000),),
        )

    def progress(done: int, total: int) -> None:
        assert total == 3
        if done == 1:
            token.cancel()

    with pytest.raises(TranscriptionCancelled):
        transcribe_chunks(
            asset,
            tmp_path,
            key,
            produce,
            chunk_ms=10000,
            decoder=lambda source, destination, start, end: None,
            cancellation=token,
            on_progress=progress,
        )
    result = transcribe_chunks(
        asset,
        tmp_path,
        key,
        produce,
        chunk_ms=10000,
        decoder=lambda source, destination, start, end: None,
    )
    assert calls == [12000, 14000, 7000]
    assert [w.start_ms for w in result.words] == [2500, 10500, 20500]
    transcribe_chunks(
        asset,
        tmp_path,
        replace(key, model="other"),
        produce,
        chunk_ms=10000,
        decoder=lambda source, destination, start, end: None,
    )
    assert len(calls) == 6


def test_chunk_merge_preserves_utterance_boundaries_with_new_word_ids(
    tmp_path: Path,
) -> None:
    from minicut.transcript import Utterance

    asset = MediaAsset("a", "/source.wav", 20000, (), "fingerprint")
    key = TranscriptionCacheKey("fingerprint", "mlx", "test", "zh", None)

    def produce(chunk: MediaAsset) -> Transcript:
        return Transcript(
            "t",
            TranscriptSource("a", "mlx", "test"),
            "zh",
            (Word("one", "提问", 2500, 3000), Word("two", "回答", 3200, 3700)),
            (
                Utterance("u1", "提问", 2500, 3000, ("one",)),
                Utterance("u2", "回答", 3200, 3700, ("two",)),
            ),
        )

    result = transcribe_chunks(
        asset,
        tmp_path,
        key,
        produce,
        chunk_ms=10000,
        decoder=lambda source, destination, start, end: None,
    )
    assert [(u.start_ms, u.end_ms) for u in result.utterances] == [
        (2500, 3000),
        (3200, 3700),
        (10500, 11000),
        (11200, 11700),
    ]
    assert tuple(
        identity for u in result.utterances for identity in u.word_ids
    ) == tuple(w.word_id for w in result.words)
    assert len({u.utterance_id for u in result.utterances}) == 4
