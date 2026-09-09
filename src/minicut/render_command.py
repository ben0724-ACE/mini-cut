"""Pure FFmpeg command construction from validated timelines."""

from dataclasses import dataclass

from minicut.media import MediaAsset, StreamType
from minicut.timeline import Timeline
from minicut.timeline_validation import (
    TimelineTrackRequirements,
    validate_timeline_for_render,
)


def _seconds(milliseconds: int) -> str:
    return f"{milliseconds / 1000:.3f}"


def _first_stream_index(asset: MediaAsset, stream_type: StreamType) -> int:
    return min(
        stream.index for stream in asset.streams if stream.stream_type is stream_type
    )


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

    def build_multi_clip(
        self,
        timeline: Timeline,
        assets: tuple[MediaAsset, ...],
        output_path: str,
        requirements: TimelineTrackRequirements,
    ) -> tuple[str, ...]:
        """Build a trim-and-concat filter graph for two or more clips."""
        if len(timeline.clips) < 2:
            raise ValueError("multi-clip render requires at least two clips")
        if not output_path:
            raise ValueError("render output path must not be empty")
        validate_timeline_for_render(timeline, assets, requirements)

        assets_by_id = {asset.asset_id: asset for asset in assets}
        referenced_asset_ids = tuple(
            dict.fromkeys(clip.source_asset_id for clip in timeline.clips)
        )
        input_indexes = {
            asset_id: index for index, asset_id in enumerate(referenced_asset_ids)
        }
        command: list[str] = [self.executable, "-nostdin", "-y"]
        for asset_id in referenced_asset_ids:
            command.extend(("-i", assets_by_id[asset_id].source_path))

        filters: list[str] = []
        concat_inputs: list[str] = []
        for clip_index, clip in enumerate(timeline.clips):
            asset = assets_by_id[clip.source_asset_id]
            input_index = input_indexes[clip.source_asset_id]
            start = _seconds(clip.source_range.start_ms)
            end = _seconds(clip.source_range.end_ms)
            if requirements.require_video:
                stream_index = _first_stream_index(asset, StreamType.VIDEO)
                filters.append(
                    f"[{input_index}:{stream_index}]trim=start={start}:end={end},"
                    f"setpts=PTS-STARTPTS[v{clip_index}]"
                )
                concat_inputs.append(f"[v{clip_index}]")
            if requirements.require_audio:
                stream_index = _first_stream_index(asset, StreamType.AUDIO)
                filters.append(
                    f"[{input_index}:{stream_index}]atrim=start={start}:end={end},"
                    f"asetpts=PTS-STARTPTS[a{clip_index}]"
                )
                concat_inputs.append(f"[a{clip_index}]")

        video_outputs = 1 if requirements.require_video else 0
        audio_outputs = 1 if requirements.require_audio else 0
        output_labels = "[outv]" if video_outputs else ""
        output_labels += "[outa]" if audio_outputs else ""
        filters.append(
            f"{''.join(concat_inputs)}concat=n={len(timeline.clips)}:"
            f"v={video_outputs}:a={audio_outputs}{output_labels}"
        )
        command.extend(("-filter_complex", ";".join(filters)))
        if video_outputs:
            command.extend(("-map", "[outv]"))
        if audio_outputs:
            command.extend(("-map", "[outa]"))
        command.append(output_path)
        return tuple(command)


__all__ = ["RenderCommandBuilder"]
