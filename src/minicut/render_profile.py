"""User-selected geometry shared by single and concatenated video rendering."""

import json
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from minicut.errors import ProcessingError
from minicut.render_command import VideoOutputMetadata


def source_dimensions(path: Path) -> tuple[int, int]:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height,sample_aspect_ratio:stream_side_data=rotation",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        stream = json.loads(result.stdout)["streams"][0]
        sar = stream.get("sample_aspect_ratio", "1:1")
        width = (
            round(int(stream["width"]) * Fraction(sar.replace(":", "/")))
            if sar not in {"N/A", "0:1"}
            else int(stream["width"])
        )
        height = int(stream["height"])
        rotation = next(
            (
                float(data["rotation"])
                for data in stream.get("side_data_list", [])
                if "rotation" in data
            ),
            0,
        )
        return (height, width) if abs(rotation) % 180 == 90 else (width, height)
    except (
        OSError,
        subprocess.SubprocessError,
        ValueError,
        KeyError,
        IndexError,
        TypeError,
    ) as error:
        raise ProcessingError("Cannot read source video dimensions") from error


@dataclass(frozen=True, slots=True)
class RenderProfile:
    aspect_ratio: str = "original"
    resolution: int = 1080
    fit: str = "pad"

    def __post_init__(self) -> None:
        if self.aspect_ratio not in {"original", "16:9", "9:16", "1:1", "4:5"}:
            raise ValueError("Unsupported aspect ratio")
        if self.resolution not in {720, 1080} or self.fit not in {"pad", "crop"}:
            raise ValueError("Unsupported resolution or fit strategy")

    def metadata(self, width: int, height: int) -> VideoOutputMetadata:
        if width <= 0 or height <= 0:
            raise ValueError("Source dimensions must be positive")
        short = self.resolution
        if self.aspect_ratio == "original":
            scale = min(1, (short * 16 / 9) / max(width, height))
            return VideoOutputMetadata(
                max(2, int(width * scale) // 2 * 2),
                max(2, int(height * scale) // 2 * 2),
                fit=self.fit,
            )
        dimensions = {
            "16:9": (short * 16 // 9, short),
            "9:16": (short, short * 16 // 9),
            "1:1": (short, short),
            "4:5": (short, short * 5 // 4),
        }
        w, h = dimensions[self.aspect_ratio]
        return VideoOutputMetadata(w, h, fit=self.fit)
