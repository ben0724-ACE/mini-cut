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
