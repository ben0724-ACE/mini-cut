import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import minicut.render_profile as profile_module
from minicut.render_profile import RenderProfile, source_dimensions


@pytest.mark.parametrize(
    "ratio,size",
    [
        ("16:9", (1280, 720)),
        ("9:16", (720, 1280)),
        ("1:1", (720, 720)),
        ("4:5", (720, 900)),
    ],
)
def test_dimensions(ratio: str, size: tuple[int, int]) -> None:
    metadata = RenderProfile(ratio, 720).metadata(1920, 1080)
    assert (metadata.width, metadata.height) == size


def test_original_does_not_upscale_and_is_even() -> None:
    metadata = RenderProfile().metadata(641, 481)
    assert (metadata.width, metadata.height) == (640, 480)
    assert RenderProfile("original", 720).metadata(3840, 2160).width == 1280


@pytest.mark.parametrize(
    "args", [("bad", 720, "pad"), ("1:1", 360, "pad"), ("1:1", 720, "stretch")]
)
def test_invalid(args: tuple[str, int, str]) -> None:
    with pytest.raises(ValueError):
        RenderProfile(*args)


@pytest.mark.parametrize(
    "ratio,size",
    [
        ("16:9", (1920, 1080)),
        ("9:16", (1080, 1920)),
        ("1:1", (1080, 1080)),
        ("4:5", (1080, 1350)),
    ],
)
def test_1080_dimensions_and_crop(ratio: str, size: tuple[int, int]) -> None:
    metadata = RenderProfile(ratio, 1080, "crop").metadata(1280, 720)
    assert (metadata.width, metadata.height) == size
    assert metadata.fit == "crop"


def test_source_display_dimensions_include_sar_and_rotation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(*args: object, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            stdout=json.dumps(
                {
                    "streams": [
                        {
                            "width": 720,
                            "height": 480,
                            "sample_aspect_ratio": "4:3",
                            "side_data_list": [{"rotation": 90}],
                        }
                    ]
                }
            )
        )

    monkeypatch.setattr(profile_module.subprocess, "run", fake_run)
    assert source_dimensions(Path("source.mov")) == (480, 960)


def test_free_crop_changes_original_dimensions_before_fixed_ratio_fit() -> None:
    profile = RenderProfile(crop_left=10, crop_right=20, crop_top=5, crop_bottom=15)
    metadata = profile.metadata(1000, 500)
    assert (metadata.width, metadata.height) == (700, 400)
    assert metadata.crop_edges == (10, 20, 5, 15)
    assert RenderProfile("1:1", 720, crop_left=50).metadata(1000, 500).width == 720


@pytest.mark.parametrize(
    "edges", [(60, 40, 0, 0), (0, 0, -1, 0), (0, 0, float("nan"), 0)]
)
def test_invalid_crop_rejected(edges: tuple[float, float, float, float]) -> None:
    from minicut.api import OutputExportBody

    with pytest.raises(ValueError):
        RenderProfile(
            crop_left=edges[0],
            crop_right=edges[1],
            crop_top=edges[2],
            crop_bottom=edges[3],
        )
    with pytest.raises(ValueError):
        OutputExportBody(
            collection_id="c",
            output_id="o",
            revision=1,
            crop_left=edges[0],
            crop_right=edges[1],
            crop_top=edges[2],
            crop_bottom=edges[3],
        )
