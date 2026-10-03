from dataclasses import asdict, replace
from pathlib import Path

import pytest

from minicut.output_plan import OutputItem, OutputPlan, OutputRole
from minicut.subtitle_ass import render_translated_ass
from minicut.subtitle_font import SubtitleFont
from minicut.subtitle_layout import SubtitleGeometry
from minicut.subtitle_pages import SubtitlePage
from minicut.subtitle_style import SubtitleStyle


def test_saved_style_round_trip_and_legacy_layout_are_independent() -> None:
    legacy = OutputPlan("v", "c", "Title", (OutputItem("i", "s", OutputRole.BODY),))
    assert OutputPlan.from_dict(legacy.to_dict()) == legacy
    assert legacy.subtitle_style is None
    style = SubtitleStyle(source_size=72, translation_size=54, background_enabled=True)
    saved = replace(legacy, revision=2, subtitle_style=style)
    assert OutputPlan.from_dict(saved.to_dict()) == saved
    # Existing data predates subtitle_style entirely.
    old_data = legacy.to_dict()
    del old_data["subtitle_style"]
    assert OutputPlan.from_dict(old_data) == legacy
    assert SubtitleGeometry.for_output(1080, 1920, legacy).source_large == 79
    assert SubtitleGeometry.for_output(1080, 1920, saved).source_large == 72


@pytest.mark.parametrize("portrait", [True, False])
def test_short_side_sizes_and_effect_margins_scale_together(portrait: bool) -> None:
    plan = OutputPlan(
        "v",
        "c",
        "Title",
        (OutputItem("i", "s", OutputRole.BODY),),
        subtitle_style=SubtitleStyle(
            source_size=72,
            translation_size=54,
            stroke_width=6,
            shadow_width=3,
            background_enabled=True,
        ),
    )
    layouts = [
        SubtitleGeometry.for_output(
            *((short, short * 16 // 9) if portrait else (short * 16 // 9, short)), plan
        )
        for short in (720, 1080)
    ]
    assert [layout.sizes("zh") for layout in layouts] == [(48, 36), (72, 54)]
    assert all(layout.sizes("zh") == layout.sizes("en") for layout in layouts)
    assert layouts[0].effect_padding == round(layouts[1].effect_padding * 2 / 3)
    assert layouts[0].row_height(48) == pytest.approx(
        layouts[1].row_height(72) * 2 / 3, abs=1
    )


@pytest.mark.parametrize(
    "patch",
    [
        {"source_size": True},
        {"translation_size": 15},
        {"source_size": 48.5},
        {"stroke_width": 13},
        {"shadow_width": -1},
        {"background_opacity": 101},
        {"background_color": "#bad"},
        {"source_font_id": "../../etc/font"},
        {"translation_font_id": "../../etc/font"},
    ],
)
def test_invalid_styles_are_rejected(patch: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        SubtitleStyle.from_dict({**asdict(SubtitleStyle()), **patch})


def test_background_is_independent_of_stroke_and_text_is_escaped() -> None:
    font = SubtitleFont("Test", Path("/missing.ttf"))
    pages = (SubtitlePage(0, 1000, "{text}", "你好", "zh"),)
    plan = OutputPlan(
        "v",
        "c",
        "Title",
        (OutputItem("i", "s", OutputRole.BODY),),
        subtitle_style=SubtitleStyle(
            text_color="#123456",
            stroke_color="#654321",
            stroke_width=0,
            bold=False,
            background_enabled=True,
            background_opacity=50,
        ),
    )
    rendered = render_translated_ass(pages, 1080, 1920, font, plan)
    assert "&H00563412" in rendered and "&H00214365" in rendered
    assert r"\1a&H80&\p1" in rendered
    assert r"\{text\}" in rendered
    no_box = render_translated_ass(
        pages,
        1080,
        1920,
        font,
        replace(plan, subtitle_style=SubtitleStyle(background_enabled=False)),
    )
    assert r"\p1" not in no_box


def test_legacy_shared_font_loads_into_both_languages_without_overriding_new_choices() -> (
    None
):
    shared = SubtitleStyle.from_dict({"font_id": "songti", "source_size": 72})
    assert shared.source_font_id == shared.translation_font_id == "songti"
    assert shared.source_size == 72
    independent = SubtitleStyle.from_dict(
        {
            "font_id": "songti",
            "source_font_id": None,
            "translation_font_id": "heiti",
        }
    )
    assert independent.source_font_id is None
    assert independent.translation_font_id == "heiti"
