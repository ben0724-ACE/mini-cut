from copy import deepcopy

import pytest

from minicut.mlx_whisper import MlxWhisperConfig, map_mlx_transcription


def test_zero_duration_tokens_coalesce_without_inventing_time() -> None:
    raw: dict[str, object] = {
        "language": "zh",
        "segments": [
            {
                "start": 0,
                "end": 1,
                "text": "用来了解",
                "words": [
                    {"word": "用", "start": 0, "end": 0, "probability": 0.8},
                    {"word": "来", "start": 0, "end": 0, "probability": 0.8},
                    {"word": "了解", "start": 0, "end": 1, "probability": 0.9},
                ],
            }
        ],
    }
    original = deepcopy(raw)
    with pytest.warns(RuntimeWarning, match="zero-duration"):
        result = map_mlx_transcription(raw, asset_id="asset", config=MlxWhisperConfig())
    assert [(w.text, w.start_ms, w.end_ms) for w in result.words] == [
        ("用来了解", 0, 1000)
    ]
    assert raw == original


def test_untimed_segment_is_reported_not_given_fake_timestamps() -> None:
    raw: dict[str, object] = {
        "language": "zh",
        "segments": [
            {
                "start": 0,
                "end": 1,
                "text": "好",
                "words": [{"word": "好", "start": 0, "end": 1, "probability": 0.9}],
            },
            {
                "start": 1,
                "end": 2,
                "text": "幻觉",
                "words": [{"word": "幻觉", "start": 1, "end": 1, "probability": 0.9}],
            },
        ],
    }
    with pytest.warns(RuntimeWarning):
        result = map_mlx_transcription(raw, asset_id="asset", config=MlxWhisperConfig())
    assert [w.text for w in result.words] == ["好"]


def test_empty_zero_length_decoder_segment_is_omitted() -> None:
    raw: dict[str, object] = {
        "language": "zh",
        "segments": [
            {
                "start": 0,
                "end": 1,
                "text": "好",
                "words": [{"word": "好", "start": 0, "end": 1, "probability": 0.9}],
            },
            {"start": 1, "end": 1, "text": "", "words": []},
        ],
    }
    with pytest.warns(RuntimeWarning):
        result = map_mlx_transcription(raw, asset_id="asset", config=MlxWhisperConfig())
    assert len(result.utterances) == 1
