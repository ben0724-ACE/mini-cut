from tools.highlight_trial import estimated_cost_cny


def test_revised_outputs_preserve_previous_versions() -> None:
    from tests.test_output_plan import collection
    from tools.highlight_trial import advance_output_revisions

    old = collection()
    updated = advance_output_revisions(old, old)
    assert updated.plans[0].revision == 2
    assert old.plans[0].revision == 1
    assert advance_output_revisions(old, None).plans[0].revision == 1


def test_restored_output_skips_existing_render_records() -> None:
    from pathlib import Path
    from tempfile import TemporaryDirectory

    from minicut.output_repository import OutputCollectionRepository
    from tests.test_output_plan import collection
    from tools.highlight_trial import advance_output_revisions

    with TemporaryDirectory() as directory:
        repo = OutputCollectionRepository(Path(directory), "selected")
        repo.write_render_record("video-1", 1, {})
        repo.write_render_record("video-1", 2, {})
        updated = advance_output_revisions(collection(), None, repository=repo)
        assert updated.plans[0].revision == 3


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
