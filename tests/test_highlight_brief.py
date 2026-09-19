import pytest

from minicut.highlight_brief import HighlightBrief, HighlightPreset


def test_defaults_and_explicit_overrides() -> None:
    clean = HighlightBrief.for_preset(HighlightPreset.CLEAN_SPEECH)
    assert (clean.count, clean.min_ms, clean.max_ms, clean.hook_ms) == (
        1,
        None,
        None,
        None,
    )
    for preset in (HighlightPreset.PODCAST, HighlightPreset.KNOWLEDGE):
        brief = HighlightBrief.for_preset(preset)
        assert (brief.count, brief.min_ms, brief.max_ms, brief.hook_ms) == (
            3,
            60000,
            90000,
            None,
        )
    opinion = HighlightBrief.for_preset(HighlightPreset.OPINION)
    assert (opinion.min_ms, opinion.max_ms, opinion.hook_ms) == (30000, 60000, None)
    custom = HighlightBrief.for_preset(
        HighlightPreset.PODCAST, count=2, instructions="只选技术解释"
    )
    assert custom.count == 2
    assert custom.instructions == "只选技术解释"
    assert custom.max_source_overlap == 0.3


@pytest.mark.parametrize(
    "kwargs",
    [
        {"count": 0},
        {"count": True},
        {"min_ms": 100000},
        {"hook_ms": 0},
        {"max_source_overlap": 1.1},
    ],
)
def test_invalid_parameters(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        HighlightBrief.for_preset(HighlightPreset.PODCAST, **kwargs)


def test_editable_preset_prompt_is_sent_to_model_payload() -> None:
    brief = HighlightBrief.for_preset(HighlightPreset.PODCAST)
    assert "故事" in str(brief.to_dict()["preset_prompt"])
    custom = HighlightBrief.for_preset(
        HighlightPreset.PODCAST, preset_prompt="只选完整的幽默故事"
    )
    assert custom.to_dict()["preset_prompt"] == "只选完整的幽默故事"


@pytest.mark.parametrize("duration", [999, 60001, True])
def test_custom_hook_limits_match_api(duration: int) -> None:
    from minicut.api import HighlightTaskBody

    with pytest.raises(ValueError):
        HighlightBrief.for_preset(HighlightPreset.PODCAST, hook_ms=duration)
    with pytest.raises(ValueError):
        HighlightTaskBody(
            asset_id="a", preset=HighlightPreset.PODCAST, count=1, hook_ms=duration
        )
