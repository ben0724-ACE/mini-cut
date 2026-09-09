"""Pure FFmpeg command construction from validated timelines."""

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from minicut.media import MediaAsset, StreamType
from minicut.timeline import Timeline
from minicut.timeline_validation import (
    TimelineTrackRequirements,
    validate_timeline_for_render,
)


def _seconds(milliseconds: int) -> str:
    return f"{milliseconds / 1000:.3f}"


def _local_file_url(path: str, *, label: str) -> str:
    if not path or "\0" in path:
        raise ValueError(f"{label} path must be a valid local path")
    return Path(path).absolute().as_uri()


def _first_stream_index(asset: MediaAsset, stream_type: StreamType) -> int:
    return min(
        stream.index for stream in asset.streams if stream.stream_type is stream_type
    )


@dataclass(frozen=True, slots=True)
class VideoOutputMetadata:
    """Normalized output geometry and frame rate for concat compatibility."""

    width: int = 1920
    height: int = 1080
    frame_rate: str = "30"

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("video output dimensions must be positive")
        if self.width % 2 or self.height % 2:
            raise ValueError("video output dimensions must be even")
        try:
            frame_rate = Fraction(self.frame_rate)
        except (ValueError, ZeroDivisionError) as error:
            raise ValueError("video output frame rate must be valid") from error
        if frame_rate <= 0:
            raise ValueError("video output frame rate must be positive")


@dataclass(frozen=True, slots=True)
class RenderEncoding:
    """Explicit codecs and pixel format for the reliable render path."""

    video_codec: str = "libx264"
    audio_codec: str = "aac"
    pixel_format: str = "yuv420p"

    def __post_init__(self) -> None:
        values = (self.video_codec, self.audio_codec, self.pixel_format)
        if any(not value.strip() for value in values):
            raise ValueError("render encoding values must not be blank")


_DEFAULT_VIDEO_METADATA = VideoOutputMetadata()
_DEFAULT_ENCODING = RenderEncoding()


def _encoding_arguments(
    *,
    include_video: bool,
    include_audio: bool,
    encoding: RenderEncoding,
) -> tuple[str, ...]:
    arguments: list[str] = []
    if include_video:
        arguments.extend(
            ("-c:v", encoding.video_codec, "-pix_fmt", encoding.pixel_format)
        )
    if include_audio:
        arguments.extend(("-c:a", encoding.audio_codec))
    return tuple(arguments)


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
        encoding: RenderEncoding = _DEFAULT_ENCODING,
    ) -> tuple[str, ...]:
        """Build an exact single-clip input-seek command as an argv tuple."""
        if len(timeline.clips) != 1:
            raise ValueError("single-clip render requires exactly one clip")
        output_url = _local_file_url(output_path, label="render output")

        clip = timeline.clips[0]
        matching_assets = tuple(
            asset for asset in assets if asset.asset_id == clip.source_asset_id
        )
        if len(matching_assets) != 1:
            raise ValueError("clip must reference exactly one known media asset")
        asset = matching_assets[0]
        stream_types = {stream.stream_type for stream in asset.streams}
        return (
            self.executable,
            "-nostdin",
            "-y",
            "-ss",
            _seconds(clip.source_range.start_ms),
            "-i",
            _local_file_url(asset.source_path, label="media source"),
            "-t",
            _seconds(clip.source_range.duration_ms),
            *_encoding_arguments(
                include_video=StreamType.VIDEO in stream_types,
                include_audio=StreamType.AUDIO in stream_types,
                encoding=encoding,
            ),
            output_url,
        )

    def build_multi_clip(
        self,
        timeline: Timeline,
        assets: tuple[MediaAsset, ...],
        output_path: str,
        requirements: TimelineTrackRequirements,
        video_metadata: VideoOutputMetadata = _DEFAULT_VIDEO_METADATA,
        encoding: RenderEncoding = _DEFAULT_ENCODING,
    ) -> tuple[str, ...]:
        """Build a trim-and-concat filter graph for two or more clips."""
        if len(timeline.clips) < 2:
            raise ValueError("multi-clip render requires at least two clips")
        output_url = _local_file_url(output_path, label="render output")
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
            source_url = _local_file_url(
                assets_by_id[asset_id].source_path,
                label="media source",
            )
            command.extend(("-i", source_url))

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
                    f"setpts=PTS-STARTPTS,"
                    f"scale={video_metadata.width}:{video_metadata.height}:"
                    "force_original_aspect_ratio=decrease,"
                    f"pad={video_metadata.width}:{video_metadata.height}:"
                    "(ow-iw)/2:(oh-ih)/2,setsar=1,"
                    f"fps={video_metadata.frame_rate},"
                    f"format={encoding.pixel_format}[v{clip_index}]"
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
        command.extend(
            _encoding_arguments(
                include_video=bool(video_outputs),
                include_audio=bool(audio_outputs),
                encoding=encoding,
            )
        )
        command.append(output_url)
        return tuple(command)


__all__ = ["RenderCommandBuilder", "RenderEncoding", "VideoOutputMetadata"]
