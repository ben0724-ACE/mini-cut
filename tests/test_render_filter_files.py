from pathlib import Path
from unittest.mock import patch

import pytest

from minicut.renderer import FfmpegRenderer, RenderFailed
from tests.test_renderer import FakeProcess


@pytest.mark.parametrize("modern", [True, False])
@pytest.mark.parametrize("failure", [True, False])
def test_long_filter_files_exist_during_render_and_are_cleaned(
    modern: bool, failure: bool
) -> None:
    graph = "null," * 4000 + "null"
    script_paths: list[Path] = []

    def launch(command: tuple[str, ...]) -> FakeProcess:
        flags = (
            ("-/filter:v", "-/filter_complex")
            if modern
            else ("-filter_script:v", "-filter_complex_script")
        )
        for flag in flags:
            path = Path(command[command.index(flag) + 1])
            assert path.read_text(encoding="utf-8") == graph
            script_paths.append(path)
        assert len(" ".join(command)) < 16000
        return FakeProcess(return_code=1 if failure else 0, stderr="fixture failure")

    with patch("minicut.renderer._modern_filter_files", return_value=modern):
        renderer = FfmpegRenderer(launcher=launch)
        command = ("ffmpeg", "-vf", graph, "-filter_complex", graph, "output.mp4")
        if failure:
            with pytest.raises(RenderFailed, match="fixture failure"):
                renderer.execute(command, timeout_seconds=5)
        else:
            renderer.execute(command, timeout_seconds=5)
    assert len(script_paths) == 2
    assert all(not path.exists() for path in script_paths)
