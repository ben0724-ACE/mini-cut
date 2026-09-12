from tools.highlight_trial import estimated_cost_cny


def test_trial_cost_uses_cache_and_completion_separately() -> None:
    assert (
        estimated_cost_cny(
            {
                "prompt_tokens": 1000000,
                "prompt_cache_hit_tokens": 500000,
                "completion_tokens": 1000000,
            }
        )
        == 4.51
    )
    assert estimated_cost_cny({"prompt_tokens": 1000000}, peak=True) == 2
