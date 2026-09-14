"""Bounded audio decoding with durable per-chunk transcripts and absolute timing."""

import subprocess
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from minicut.errors import ProcessingError
from minicut.media import MediaAsset
from minicut.transcript import (
    Transcript,
    Word,
    generate_transcript_id,
    generate_word_id,
)
from minicut.transcription_cache import TranscriptCacheRepository, TranscriptionCacheKey
from minicut.transcription_task import CancellationToken

CHUNK_MS = 300_000
OVERLAP_MS = 2_000


def decode_chunk(source: str, destination: Path, start: int, end: int) -> None:
    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-ss",
                str(start / 1000),
                "-i",
                source,
                "-t",
                str((end - start) / 1000),
                "-map",
                "0:a:0",
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                "-y",
                str(destination),
            ],
            capture_output=True,
            timeout=180,
            check=False,
        )
        if result.returncode:
            raise ProcessingError(
                "Audio chunk decoding failed; check the source audio and free disk space"
            )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ProcessingError("Audio chunk decoding failed or timed out") from error


def transcribe_chunks(
    asset: MediaAsset,
    directory: Path,
    key: TranscriptionCacheKey,
    producer: Callable[[MediaAsset], Transcript],
    *,
    cancellation: CancellationToken | None = None,
    on_progress: Callable[[int, int], None] = lambda done, total: None,
    decoder: Callable[[str, Path, int, int], None] = decode_chunk,
    chunk_ms: int = CHUNK_MS,
) -> Transcript:
    if chunk_ms <= OVERLAP_MS * 2:
        raise ValueError("chunk size must exceed the overlap")
    token = cancellation or CancellationToken()
    directory.mkdir(parents=True, exist_ok=True)
    total = (asset.duration_ms + chunk_ms - 1) // chunk_ms
    words: list[Word] = []
    source = None
    language = key.language
    transcript_id = ""
    for index, start in enumerate(range(0, asset.duration_ms, chunk_ms)):
        token.raise_if_cancelled()
        end = min(start + chunk_ms, asset.duration_ms)
        decode_start, decode_end = (
            max(0, start - OVERLAP_MS),
            min(asset.duration_ms, end + OVERLAP_MS),
        )
        cache = TranscriptCacheRepository(
            directory / f"v1-{chunk_ms}-{decode_start}-{decode_end}.json"
        )
        chunk = cache.read(key)
        if chunk is None:
            with TemporaryDirectory(prefix="audio-", dir=directory) as temporary:
                path = Path(temporary) / "chunk.wav"
                decoder(asset.source_path, path, decode_start, decode_end)
                token.raise_if_cancelled()
                chunk = producer(
                    replace(
                        asset,
                        source_path=str(path),
                        duration_ms=decode_end - decode_start,
                    )
                )
                cache.write(key, chunk)
        source = chunk.source
        transcript_id = generate_transcript_id(source, language)
        for word in chunk.words:
            first, last = word.start_ms + decode_start, word.end_ms + decode_start
            center = (first + last) / 2
            if not start <= center < end:
                continue
            if first < 0 or last > asset.duration_ms:
                continue
            # Overlap inference can shift the same boundary token across ownership.
            if words and first < words[-1].end_ms:
                if word.text.strip().casefold() == words[-1].text.strip().casefold():
                    continue
                if first < words[-1].start_ms:
                    raise ProcessingError(
                        "Chunk boundary timing conflicts; review or retranscribe this boundary"
                    )
            words.append(
                replace(
                    word,
                    start_ms=first,
                    end_ms=last,
                    word_id=generate_word_id(
                        transcript_id,
                        len(words),
                        text=word.text,
                        start_ms=first,
                        end_ms=last,
                    ),
                )
            )
        on_progress(index + 1, total)
        token.raise_if_cancelled()
    if source is None or not words:
        raise ProcessingError("No timestamped speech found in audio chunks")
    return Transcript(transcript_id, source, language, tuple(words))
