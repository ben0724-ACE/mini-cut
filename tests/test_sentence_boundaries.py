from minicut.sentence_boundaries import complete_range, sentence_segments
from minicut.transcript import Transcript, TranscriptSource, Word


def test_size_limit_is_not_a_sentence_boundary_and_expands_to_pause() -> None:
    words = tuple(
        Word(f"w{i}", "内容", i * 1000, i * 1000 + 900) for i in range(20)
    ) + (Word("last", "结尾。", 22000, 23000),)
    transcript = Transcript("t", TranscriptSource("a", "test", "test"), "zh", words)
    segments = sentence_segments(transcript)
    assert segments[0].segment_id.endswith("e0")
    assert "-s0-" in segments[1].segment_id
    start, end, notes = complete_range([segments[0]], segments)
    assert (start, end) == (0, 20000)
    assert notes == ()
    assert tuple(w for s in segments for w in s.word_ids) == tuple(
        w.word_id for w in words
    )


def test_unpunctuated_speech_reports_uncertain_boundary_after_ten_seconds() -> None:
    transcript = Transcript(
        "t",
        TranscriptSource("a", "test", "test"),
        "zh",
        tuple(Word(f"w{i}", "内容", i * 1000, i * 1000 + 900) for i in range(60)),
    )
    segments = sentence_segments(transcript)
    _, _, notes = complete_range([segments[1]], segments)
    assert len(notes) == 2
