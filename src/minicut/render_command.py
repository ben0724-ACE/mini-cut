"""Pure FFmpeg command construction from validated timelines."""

from dataclasses import dataclass

from minicut.media import MediaAsset
from minicut.timeline import Timeline


def _seconds(milliseconds: int) -> str:
    return f"{milliseconds / 1000:.3f}"


@dataclass(frozen=True, slots=True)
class RenderCommandBuilder:
    """Build FFmpeg argv without invoking a shell or process."""

    executable: str = "ffmpeg"

    def __post_init__(self) -> None:
        if not self.executable.strip():
            raise ValueError("FFmpeg executable must not be blank")

    def build_single_clip(
        self,
        timeline: Timeline,
        assets: tuple[MediaAsset, ...],
        output_path: str,
    ) -> tuple[str, ...]:
        """Build an exact single-clip input-seek command as an argv tuple."""
        if len(timeline.clips) != 1:
            raise ValueError("single-clip render requires exactly one clip")
        if not output_path:
            raise ValueError("render output path must not be empty")

        clip = timeline.clips[0]
        matching_assets = tuple(
            asset for asset in assets if asset.asset_id == clip.source_asset_id
        )
        if len(matching_assets) != 1:
            raise ValueError("clip must reference exactly one known media asset")
        asset = matching_assets[0]
        return (
            self.executable,
            "-nostdin",
            "-y",
            "-ss",
            _seconds(clip.source_range.start_ms),
            "-i",
            asset.source_path,
            "-t",
            _seconds(clip.source_range.duration_ms),
            output_path,
        )


__all__ = ["RenderCommandBuilder"]
