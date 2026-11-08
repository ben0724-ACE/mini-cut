"""Pure FFmpeg command construction from validated timelines."""

from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction
from math import ceil, isfinite
from pathlib import Path

from minicut.ffmpeg_paths import ffmpeg_file
from minicut.media import MediaAsset, StreamType
from minicut.output_plan import OutputPlan, OutputRole, transition_gap_ms
from minicut.output_timeline import coalesce_output_media, validate_output_timeline
from minicut.semantic_segment import SemanticSegment
from minicut.subtitle_font import SubtitleFont
from minicut.timeline import Timeline
from minicut.timeline_validation import (
    TimelineTrackRequirements,
    validate_timeline_for_render,
)


def _sum_expressions(values: tuple[str, ...]) -> str:
    # FFmpeg's expression parser has a nesting limit. A flat, left-associative
    # sum with hundreds of cuts exceeds it; a balanced tree has logarithmic depth.
    if not values:
        return "0"
    if len(values) == 1:
        return values[0]
    middle = len(values) // 2
    return f"({_sum_expressions(values[:middle])}+{_sum_expressions(values[middle:])})"


def _seconds(milliseconds: int) -> str:
    return f"{milliseconds / 1000:.3f}"


def _local_file_url(path: str, *, label: str) -> str:
    if not path or "\0" in path:
        raise ValueError(f"{label} path must be a valid local path")
    return ffmpeg_file(path)


def _source_crop(metadata: "VideoOutputMetadata") -> str:
    left, right, top, bottom = metadata.crop_edges
    if not any(metadata.crop_edges):
        return ""
    return (
        "scale=trunc(iw*sar/2)*2:ih,setsar=1,"
        f"crop=w='max(2,trunc(iw*{(100 - left - right) / 100:.8f}/2)*2)':"
        f"h='max(2,trunc(ih*{(100 - top - bottom) / 100:.8f}/2)*2)':"
        f"x='trunc(iw*{left / 100:.8f}/2)*2':y='trunc(ih*{top / 100:.8f}/2)*2',"
    )


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
    fit: str = "pad"
    crop_edges: tuple[float, float, float, float] = (0, 0, 0, 0)

    def __post_init__(self) -> None:
        left, right, top, bottom = self.crop_edges
        if (
            any(not isfinite(v) or v < 0 for v in self.crop_edges)
            or left + right > 95
            or top + bottom > 95
        ):
            raise ValueError("裁剪范围每个方向至少保留 5% 的画面")
        if self.fit not in {"pad", "crop"}:
            raise ValueError("video fit must be pad or crop")
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


@dataclass(frozen=True, slots=True)
class AudioOutputMetadata:
    """Normalized sample rate and channel layout for concat compatibility."""

    sample_rate: int = 48_000
    channel_layout: str = "stereo"

    def __post_init__(self) -> None:
        if self.sample_rate <= 0:
            raise ValueError("audio output sample rate must be positive")
        if self.channel_layout not in {"mono", "stereo"}:
            raise ValueError("audio output channel layout must be mono or stereo")

    @property
    def channel_count(self) -> int:
        return 1 if self.channel_layout == "mono" else 2


@dataclass(frozen=True, slots=True)
class AudioFade:
    """Optional symmetric fade applied at each audio clip boundary."""

    duration_ms: int = 0

    def __post_init__(self) -> None:
        if self.duration_ms < 0:
            raise ValueError("audio fade duration must not be negative")


_DEFAULT_VIDEO_METADATA = VideoOutputMetadata()
_DEFAULT_AUDIO_METADATA = AudioOutputMetadata()
_DEFAULT_AUDIO_FADE = AudioFade()
_DEFAULT_ENCODING = RenderEncoding()


class SubtitleMode(StrEnum):
    SOFT = "soft"
    BURNED = "burned"


@dataclass(frozen=True, slots=True)
class IntroMedia:
    image_path: str
    audio_path: str
    duration_ms: int
    body_duration_ms: int
    has_body_audio: bool
    title_path: str | None = None
    text_path: str | None = None
    motion_style: str = "fade"
    motion_strength: float = 1.0
    transition_ms: int = 0


def _subtitle_filter_path(path: str) -> str:
    value = Path(path).absolute().as_posix()
    # Escape the option parser, then the enclosing filtergraph parser. A single
    # quoted string is insufficient for filenames containing an apostrophe.
    option_value = "".join(
        ("\\" if character in "\\':" else "") + character for character in value
    )
    return "".join(
        ("\\" if character in "\\'[],;" else "") + character
        for character in option_value
    )


def _burned_subtitle_filter(
    subtitle_path: str,
    font: SubtitleFont,
    metadata: VideoOutputMetadata | None,
    styled: bool,
    fonts_directory: str | None,
) -> str:
    return (
        f"subtitles=filename={_subtitle_filter_path(subtitle_path)}"
        f":fontsdir={_subtitle_filter_path(fonts_directory or str(font.path.parent))}"
        + (
            ""
            if styled
            else f":force_style='FontName={font.family}"
            + (
                "'"
                if metadata is None
                else f",FontSize={max(10, round(18 * min(1, metadata.width / metadata.height)))},MarginL=20,MarginR=20,MarginV=12'"
            )
        )
    )


def _audio_fade_filters(
    clip_duration_ms: int, audio_fade: AudioFade
) -> tuple[str, ...]:
    duration_ms = min(audio_fade.duration_ms, clip_duration_ms // 2)
    if duration_ms == 0:
        return ()
    fade_duration = _seconds(duration_ms)
    fade_out_start = _seconds(clip_duration_ms - duration_ms)
    return (
        f"afade=t=in:st=0:d={fade_duration}",
        f"afade=t=out:st={fade_out_start}:d={fade_duration}",
    )


def _encoding_arguments(
    *,
    include_video: bool,
    include_audio: bool,
    encoding: RenderEncoding,
    audio_metadata: AudioOutputMetadata,
) -> tuple[str, ...]:
    arguments: list[str] = []
    if include_video:
        arguments.extend(
            ("-c:v", encoding.video_codec, "-pix_fmt", encoding.pixel_format)
        )
    if include_audio:
        arguments.extend(
            (
                "-c:a",
                encoding.audio_codec,
                "-ar",
                str(audio_metadata.sample_rate),
                "-ac",
                str(audio_metadata.channel_count),
            )
        )
    return tuple(arguments)


@dataclass(frozen=True, slots=True)
class RenderCommandBuilder:
    """Build FFmpeg argv without invoking a shell or process."""

    executable: str = "ffmpeg"

    def __post_init__(self) -> None:
        if not self.executable.strip():
            raise ValueError("FFmpeg executable must not be blank")

    def build_subtitle_output(
        self,
        input_path: str,
        subtitle_path: str,
        output_path: str,
        mode: SubtitleMode,
        encoding: RenderEncoding = _DEFAULT_ENCODING,
        *,
        subtitle_font: SubtitleFont | None = None,
        video_metadata: VideoOutputMetadata | None = None,
        styled_subtitles: bool = False,
        subtitle_fonts_directory: str | None = None,
        worker_threads: int | None = None,
        intro_media: IntroMedia | None = None,
    ) -> tuple[str, ...]:
        """Attach a selectable track or render subtitle text into video frames."""
        input_url = _local_file_url(input_path, label="subtitle video input")
        subtitle_url = _local_file_url(subtitle_path, label="subtitle input")
        output_url = _local_file_url(output_path, label="subtitle video output")
        if worker_threads is not None and worker_threads < 1:
            raise ValueError("render worker threads must be positive")
        if intro_media is not None:
            if video_metadata is None:
                raise ValueError("Intro cards require output video dimensions")
            return self._build_intro_subtitles(
                input_url,
                subtitle_url,
                output_url,
                subtitle_path,
                mode,
                encoding,
                intro_media,
                video_metadata,
                subtitle_font,
                styled_subtitles,
                subtitle_fonts_directory,
                worker_threads,
            )
        command = [self.executable, "-nostdin", "-y"]
        if worker_threads is not None:
            command.extend(
                (
                    "-filter_threads",
                    str(worker_threads),
                    "-threads",
                    str(worker_threads),
                )
            )
        command.extend(("-i", input_url))
        if mode is SubtitleMode.SOFT:
            command.extend(
                (
                    "-i",
                    subtitle_url,
                    "-map",
                    "0:v?",
                    "-map",
                    "0:a?",
                    "-map",
                    "1:0",
                    "-c:v",
                    "copy",
                    "-c:a",
                    "copy",
                    "-c:s",
                    "mov_text",
                    "-metadata:s:s:0",
                    "language=zho",
                )
            )
        elif mode is SubtitleMode.BURNED:
            if subtitle_font is None:
                raise ValueError("Burned subtitles require an explicit CJK font")
            subtitle_filter = _burned_subtitle_filter(
                subtitle_path,
                subtitle_font,
                video_metadata,
                styled_subtitles,
                subtitle_fonts_directory,
            )
            command.extend(
                (
                    "-vf",
                    subtitle_filter,
                    "-map",
                    "0:v:0",
                    "-map",
                    "0:a?",
                    "-c:v",
                    encoding.video_codec,
                    "-pix_fmt",
                    encoding.pixel_format,
                    "-c:a",
                    "copy",
                )
            )
        else:
            raise ValueError("unsupported subtitle output mode")
        if worker_threads is not None and mode is SubtitleMode.BURNED:
            command.extend(("-threads", str(worker_threads)))
            if encoding.video_codec == "libx264":
                command.extend(("-preset", "veryfast"))
        command.append(output_url)
        return tuple(command)

    def _build_intro_subtitles(
        self,
        input_url: str,
        subtitle_url: str,
        output_url: str,
        subtitle_path: str,
        mode: SubtitleMode,
        encoding: RenderEncoding,
        intro: IntroMedia,
        metadata: VideoOutputMetadata,
        font: SubtitleFont | None,
        styled: bool,
        fonts_directory: str | None,
        worker_threads: int | None,
    ) -> tuple[str, ...]:
        """Prepend the card during the existing subtitle pass, with one audio clock."""
        duration, body = _seconds(intro.duration_ms), _seconds(intro.body_duration_ms)
        command = [
            self.executable,
            "-nostdin",
            "-y",
            "-filter_complex_threads",
            "2",
            "-i",
            input_url,
            "-loop",
            "1",
            "-framerate",
            metadata.frame_rate,
            "-t",
            duration,
            "-i",
            _local_file_url(intro.image_path, label="intro image"),
            "-i",
            _local_file_url(intro.audio_path, label="intro audio"),
        ]
        if mode is SubtitleMode.SOFT:
            command.extend(("-i", subtitle_url))
        layers: list[tuple[int, str]] = []
        next_input = 4 if mode is SubtitleMode.SOFT else 3
        for layer_path, delay in ((intro.title_path, "0"), (intro.text_path, "0.2")):
            if layer_path is not None:
                command.extend(
                    (
                        "-loop",
                        "1",
                        "-framerate",
                        metadata.frame_rate,
                        "-t",
                        duration,
                        "-i",
                        _local_file_url(layer_path, label="intro text layer"),
                    )
                )
                layers.append((next_input, delay))
                next_input += 1
        background_effect = ""
        if layers:
            frames = max(
                2, ceil(intro.duration_ms / 1000 * float(Fraction(metadata.frame_rate)))
            )
            zoom = f"1+{0.02 * intro.motion_strength:g}*on/{frames - 1}"
            camera_x = "iw/2-iw/zoom/2"
            if intro.motion_style == "rise":
                zoom = f"1+{0.045 * intro.motion_strength:g}*(1-cos(3.141592654*on/{frames - 1}))/2"
                camera_x += f"+(iw-iw/zoom)*0.2*sin(3.141592654*on/{frames - 1})"
            background_effect = (
                f"scale={metadata.width * 2}:{metadata.height * 2},"
                f"zoompan=z='{zoom}':x='{camera_x}':y='ih/2-ih/zoom/2':"
                f"d=1:s={metadata.width}x{metadata.height}:fps={metadata.frame_rate},"
            )
        graph = [
            f"[1:v]{background_effect}fps={metadata.frame_rate},trim=duration={duration},setpts=PTS-STARTPTS,setsar=1,format=yuv420p[ibg]",
            f"[0:v]trim=duration={body},setpts=PTS-STARTPTS,setsar=1,format=yuv420p[bv]",
            f"[2:a]atrim=duration={duration},asetpts=PTS-STARTPTS,aformat=sample_rates=48000:channel_layouts=stereo[ia]",
            (
                "[0:a:0]aresample=48000,aformat=channel_layouts=stereo,apad,"
                if intro.has_body_audio
                else "anullsrc=r=48000:cl=stereo,"
            )
            + f"atrim=duration={body},asetpts=PTS-STARTPTS[ba]",
        ]
        background_label = "ibg"
        for ordinal, (input_index, delay) in enumerate(layers):
            position = "0"
            fade_in = "0.35"
            if intro.motion_style == "rise":
                travel = max(
                    6,
                    round(
                        min(metadata.width, metadata.height)
                        * (0.035 if ordinal == 0 else 0.025)
                    ),
                )
                travel *= intro.motion_strength
                position = f"{travel}*pow(1-min(1,max(0,(t-{delay})/0.65)),3)"
                fade_in = "0.5"
            graph.extend(
                (
                    f"[{input_index}:v]format=rgba,setpts=PTS-STARTPTS,"
                    f"fade=t=in:st={delay}:d={fade_in}:alpha=1,"
                    f"fade=t=out:st={_seconds(intro.duration_ms - 300)}:d=0.3:alpha=1[itext{ordinal}]",
                    f"[{background_label}][itext{ordinal}]overlay=x=0:y='{position}':shortest=1:format=auto[ilayer{ordinal}]",
                )
            )
            background_label = f"ilayer{ordinal}"
        graph.extend(
            (
                f"[{background_label}]format=yuv420p[iv]",
                "[iv][ia][bv][ba]concat=n=2:v=1:a=1[v][a]",
            )
        )
        video_label = "[v]"
        if mode is SubtitleMode.BURNED:
            if font is None:
                raise ValueError("Burned subtitles require an explicit CJK font")
            graph.append(
                "[v]"
                + _burned_subtitle_filter(
                    subtitle_path, font, metadata, styled, fonts_directory
                )
                + "[outv]"
            )
            video_label = "[outv]"
        if intro.transition_ms:
            half = min(intro.transition_ms // 2, intro.body_duration_ms // 2)
            if half:
                out_start = _seconds(intro.duration_ms - half)
                fade_length = _seconds(half)
                in_end = _seconds(intro.duration_ms + half)
                graph.append(
                    f"{video_label}fade=t=out:st={out_start}:d={fade_length}:enable='between(t,{out_start},{duration})',"
                    f"fade=t=in:st={duration}:d={fade_length}:enable='between(t,{duration},{in_end})'[intro_transition]"
                )
                video_label = "[intro_transition]"
        command.extend(
            ("-filter_complex", ";".join(graph), "-map", video_label, "-map", "[a]")
        )
        if mode is SubtitleMode.SOFT:
            command.extend(
                ("-map", "3:0", "-c:s", "mov_text", "-metadata:s:s:0", "language=zho")
            )
        command.extend(
            (
                "-c:v",
                encoding.video_codec,
                "-pix_fmt",
                encoding.pixel_format,
                "-c:a",
                encoding.audio_codec,
                "-ar",
                "48000",
                "-ac",
                "2",
            )
        )
        if worker_threads is not None:
            command.extend(("-threads", str(worker_threads)))
            if encoding.video_codec == "libx264":
                command.extend(("-preset", "veryfast"))
        command.extend(("-movflags", "+faststart", output_url))
        return tuple(command)

    def build_single_clip(
        self,
        timeline: Timeline,
        assets: tuple[MediaAsset, ...],
        output_path: str,
        encoding: RenderEncoding = _DEFAULT_ENCODING,
        audio_metadata: AudioOutputMetadata = _DEFAULT_AUDIO_METADATA,
        audio_fade: AudioFade = _DEFAULT_AUDIO_FADE,
        denoise_filter: str | None = None,
        video_metadata: VideoOutputMetadata | None = None,
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
        if denoise_filter is not None and not denoise_filter.strip():
            raise ValueError("audio denoise filter must not be blank")
        audio_filters = ()
        if StreamType.AUDIO in stream_types:
            audio_filters = (
                *((denoise_filter,) if denoise_filter is not None else ()),
                *_audio_fade_filters(clip.source_range.duration_ms, audio_fade),
            )
        audio_filter_arguments = (
            ("-af", ",".join(audio_filters)) if audio_filters else ()
        )
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
            *audio_filter_arguments,
            *(
                (
                    "-vf",
                    _source_crop(video_metadata)
                    + f"scale={video_metadata.width}:{video_metadata.height}:force_original_aspect_ratio={'decrease' if video_metadata.fit == 'pad' else 'increase'},"
                    + (
                        f"pad={video_metadata.width}:{video_metadata.height}:(ow-iw)/2:(oh-ih)/2,"
                        if video_metadata.fit == "pad"
                        else f"crop={video_metadata.width}:{video_metadata.height},"
                    )
                    + f"setsar=1,fps={video_metadata.frame_rate}",
                )
                if video_metadata is not None and StreamType.VIDEO in stream_types
                else ()
            ),
            *_encoding_arguments(
                include_video=StreamType.VIDEO in stream_types,
                include_audio=StreamType.AUDIO in stream_types,
                encoding=encoding,
                audio_metadata=audio_metadata,
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
        audio_metadata: AudioOutputMetadata = _DEFAULT_AUDIO_METADATA,
        audio_fade: AudioFade = _DEFAULT_AUDIO_FADE,
        denoise_filter: str | None = None,
    ) -> tuple[str, ...]:
        """Build a trim-and-concat filter graph for two or more clips."""
        if len(timeline.clips) < 2:
            raise ValueError("multi-clip render requires at least two clips")
        validate_timeline_for_render(timeline, assets, requirements)
        return self._build_concat_arguments(
            timeline,
            assets,
            output_path,
            requirements,
            video_metadata,
            encoding,
            audio_metadata,
            audio_fade,
            denoise_filter,
        )

    def build_output_timeline(
        self,
        timeline: Timeline,
        plan: OutputPlan,
        segments: tuple[SemanticSegment, ...],
        source_asset_id: str,
        assets: tuple[MediaAsset, ...],
        output_path: str,
        requirements: TimelineTrackRequirements,
        video_metadata: VideoOutputMetadata = _DEFAULT_VIDEO_METADATA,
        encoding: RenderEncoding = _DEFAULT_ENCODING,
        audio_fade: AudioFade = _DEFAULT_AUDIO_FADE,
        denoise_filter: str | None = None,
    ) -> tuple[str, ...]:
        """Render explicit source reuse/order only after plan-bound validation."""
        validate_output_timeline(
            timeline, plan, segments, source_asset_id, assets, requirements
        )
        timeline = coalesce_output_media(timeline, plan)
        return self._build_concat_arguments(
            timeline,
            assets,
            output_path,
            requirements,
            video_metadata,
            encoding,
            _DEFAULT_AUDIO_METADATA,
            audio_fade,
            denoise_filter,
            hook_transition_ms=plan.hook_transition_ms,
            hook_transition_kind=plan.hook_transition_kind,
            hook_boundary_ms=next(
                (
                    clip.output_range.start_ms - transition_gap_ms(plan)
                    for clip in timeline.clips
                    if next(
                        item.role
                        for item in plan.items
                        if item.instance_id == clip.clip_id
                    )
                    is OutputRole.BODY
                ),
                0,
            ),
        )

    def build_cleanup_video(
        self,
        timeline: Timeline,
        asset: MediaAsset,
        output_path: str,
        metadata: VideoOutputMetadata,
    ) -> tuple[str, ...]:
        """One decoder/filter chain; cut timestamps share one output clock."""
        selected = _sum_expressions(
            tuple(
                f"gte(t,{_seconds(c.source_range.start_ms)})*lt(t,{_seconds(c.source_range.end_ms)})"
                for c in timeline.clips
            )
        )
        previous = 0
        offsets: list[str] = []
        for clip in timeline.clips:
            gap = clip.source_range.start_ms - previous
            if gap:
                offsets.append(
                    f"gte(T,{_seconds(clip.source_range.start_ms)})*{_seconds(gap)}"
                )
            previous = clip.source_range.end_ms
        removed = _sum_expressions(tuple(offsets))
        geometry = (
            f"scale={metadata.width}:{metadata.height}:force_original_aspect_ratio=decrease,"
            f"pad={metadata.width}:{metadata.height}:(ow-iw)/2:(oh-ih)/2,setsar=1,"
            if metadata.fit == "pad"
            else f"scale={metadata.width}:{metadata.height}:force_original_aspect_ratio=increase,"
            f"crop={metadata.width}:{metadata.height},setsar=1,"
        )
        filters = (
            f"settb=AVTB,select='{selected}',setpts='PTS-({removed})/TB',"
            + _source_crop(metadata)
            + geometry
            + f"format=yuv420p,fps={metadata.frame_rate}"
        )
        return (
            self.executable,
            "-nostdin",
            "-y",
            "-threads",
            "2",
            "-filter_threads",
            "2",
            "-t",
            _seconds(timeline.clips[-1].source_range.end_ms),
            "-i",
            _local_file_url(asset.source_path, label="cleanup source"),
            "-map",
            f"0:{_first_stream_index(asset, StreamType.VIDEO)}",
            "-an",
            "-vf",
            filters,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-threads",
            "2",
            "-pix_fmt",
            "yuv420p",
            _local_file_url(output_path, label="cleanup video output"),
        )

    def build_cleanup_audio(
        self,
        asset: MediaAsset,
        start_ms: int,
        duration_ms: int,
        output_path: str,
        fade: AudioFade,
        denoise_filter: str | None,
    ) -> tuple[str, ...]:
        # Seek and decode just this kept interval, then concatenate raw samples
        # on disk. Per-clip AAC padding and video-frame rounding never accumulate.
        filters = ["aresample=48000", "aformat=channel_layouts=stereo"]
        if denoise_filter:
            filters.append(denoise_filter)
        filters.extend(_audio_fade_filters(duration_ms, fade))
        filters.extend(
            (
                f"apad=whole_len={duration_ms * 48}",
                f"atrim=end_sample={duration_ms * 48}",
            )
        )
        return (
            self.executable,
            "-nostdin",
            "-y",
            "-threads",
            "2",
            "-filter_threads",
            "2",
            "-ss",
            _seconds(start_ms),
            "-vn",
            "-i",
            _local_file_url(asset.source_path, label="cleanup audio source"),
            "-map",
            f"0:{_first_stream_index(asset, StreamType.AUDIO)}",
            "-vn",
            "-af",
            ",".join(filters),
            "-c:a",
            "pcm_s16le",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-f",
            "s16le",
            _local_file_url(output_path, label="cleanup audio output"),
        )

    def build_cleanup_mux(
        self, video: Path, audio: Path, output: Path
    ) -> tuple[str, ...]:
        return (
            self.executable,
            "-nostdin",
            "-y",
            "-i",
            _local_file_url(str(video), label="cleanup video"),
            "-f",
            "s16le",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-i",
            _local_file_url(str(audio), label="cleanup samples"),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-threads",
            "2",
            _local_file_url(str(output), label="cleanup mux output"),
        )

    def _build_concat_arguments(
        self,
        timeline: Timeline,
        assets: tuple[MediaAsset, ...],
        output_path: str,
        requirements: TimelineTrackRequirements,
        video_metadata: VideoOutputMetadata,
        encoding: RenderEncoding,
        audio_metadata: AudioOutputMetadata,
        audio_fade: AudioFade,
        denoise_filter: str | None,
        hook_boundary_ms: int = 0,
        hook_transition_ms: int = 300,
        hook_transition_kind: str = "fade",
    ) -> tuple[str, ...]:
        output_url = _local_file_url(output_path, label="render output")
        if denoise_filter is not None and not denoise_filter.strip():
            raise ValueError("audio denoise filter must not be blank")

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

        # Keep audio demuxing independent of video demand. With long late cuts,
        # a shared input can exhaust the audio packet queue before video trim
        # yields its first frame, and FFmpeg may succeed without any audio.
        audio_input_indexes = dict(input_indexes)
        if requirements.require_video and requirements.require_audio:
            for offset, asset_id in enumerate(referenced_asset_ids):
                audio_input_indexes[asset_id] = len(input_indexes) + offset
                command.extend(
                    (
                        "-vn",
                        "-i",
                        _local_file_url(
                            assets_by_id[asset_id].source_path, label="audio source"
                        ),
                    )
                )

        filters: list[str] = []
        video_inputs: list[str] = []
        audio_inputs: list[str] = []
        for clip_index, clip in enumerate(timeline.clips):
            asset = assets_by_id[clip.source_asset_id]
            input_index = input_indexes[clip.source_asset_id]
            start = _seconds(clip.source_range.start_ms)
            end = _seconds(clip.source_range.end_ms)
            if requirements.require_video:
                stream_index = _first_stream_index(asset, StreamType.VIDEO)
                filters.append(
                    f"[{input_index}:{stream_index}]trim=start={start}:end={end},"
                    f"settb=AVTB,setpts=PTS-STARTPTS+{_seconds(clip.output_range.start_ms)}/TB,"
                    + _source_crop(video_metadata)
                    + f"scale={video_metadata.width}:{video_metadata.height}:"
                    + (
                        "force_original_aspect_ratio=decrease,"
                        f"pad={video_metadata.width}:{video_metadata.height}:"
                        "(ow-iw)/2:(oh-ih)/2,setsar=1,"
                        if video_metadata.fit == "pad"
                        else "force_original_aspect_ratio=increase,"
                        f"crop={video_metadata.width}:{video_metadata.height},setsar=1,"
                    )
                    + f"format={encoding.pixel_format}[v{clip_index}]"
                )
                video_inputs.append(f"[v{clip_index}]")
            if requirements.require_audio:
                stream_index = _first_stream_index(asset, StreamType.AUDIO)
                audio_filters = [
                    f"[{audio_input_indexes[clip.source_asset_id]}:{stream_index}]atrim=start={start}:end={end},"
                    "asetpts=PTS-STARTPTS,"
                    f"aresample={audio_metadata.sample_rate},"
                    f"aformat=channel_layouts={audio_metadata.channel_layout}"
                ]
                if denoise_filter is not None:
                    audio_filters.append("," + denoise_filter)
                fades = _audio_fade_filters(clip.source_range.duration_ms, audio_fade)
                if fades:
                    audio_filters.append("," + ",".join(fades))
                audio_filters.append(f"[a{clip_index}]")
                filters.append("".join(audio_filters))
                audio_inputs.append(f"[a{clip_index}]")

        if (
            hook_boundary_ms > 0
            and hook_transition_ms > 0
            and hook_transition_kind == "tv_static"
        ):
            effect_index = command.count("-i")
            effect_path = Path(__file__).parent / "assets" / "tv-static-beep.mp4"
            command.extend(
                ("-i", _local_file_url(str(effect_path), label="transition asset"))
            )
            duration = _seconds(hook_transition_ms)
            if requirements.require_video:
                filters.append(
                    f"[{effect_index}:v:0]trim=duration={duration},settb=AVTB,setpts=PTS-STARTPTS+{_seconds(hook_boundary_ms)}/TB,"
                    f"scale={video_metadata.width}:{video_metadata.height},setsar=1,format={encoding.pixel_format}[effectv]"
                )
                video_inputs.append("[effectv]")
            if requirements.require_audio:
                filters.append(
                    f"[{effect_index}:a:0]atrim=duration={duration},asetpts=PTS-STARTPTS,aresample={audio_metadata.sample_rate},"
                    f"aformat=channel_layouts={audio_metadata.channel_layout},afade=t=in:d=0.01,afade=t=out:st={_seconds(max(0, hook_transition_ms - 10))}:d=0.01[effecta]"
                )
                body_index = next(
                    i
                    for i, c in enumerate(timeline.clips)
                    if c.output_range.start_ms > hook_boundary_ms
                )
                audio_inputs.insert(body_index, "[effecta]")

        video_outputs = 1 if requirements.require_video else 0
        audio_outputs = 1 if requirements.require_audio else 0
        # Audio concatenation must not be padded to individually rounded video
        # lengths. Place video on the absolute output clock and resample frames
        # once, so per-cut rounding cannot accumulate over a long edit.
        if video_outputs:
            filters.append(
                f"{''.join(video_inputs)}interleave=nb_inputs={len(video_inputs)}:duration=longest,"
                f"fps={video_metadata.frame_rate}[outv]"
            )
        if audio_outputs:
            filters.append(
                f"{''.join(audio_inputs)}concat=n={len(audio_inputs)}:v=0:a=1[outa]"
            )
        if hook_boundary_ms > 0 and hook_transition_kind == "fade":
            # Fade through black/silence without overlapping speech or shifting subtitles.
            duration = min(
                hook_transition_ms,
                hook_boundary_ms // 2,
                (timeline.estimated_duration_ms - hook_boundary_ms) // 2,
            )
            if duration > 0:
                before, boundary, length = (
                    _seconds(hook_boundary_ms - duration),
                    _seconds(hook_boundary_ms),
                    _seconds(duration),
                )
                if video_outputs:
                    filters = [
                        value.replace("[outv]", "[prefadev]") for value in filters
                    ]
                    filters.append(
                        f"[prefadev]fade=t=out:st={before}:d={length}:enable='between(t,{before},{boundary})',fade=t=in:st={boundary}:d={length}:enable='between(t,{boundary},{_seconds(hook_boundary_ms + duration)})'[outv]"
                    )
                if audio_outputs:
                    filters = [
                        value.replace("[outa]", "[prefadea]") for value in filters
                    ]
                    filters.append(
                        f"[prefadea]afade=t=out:st={before}:d={length}:enable='between(t,{before},{boundary})',afade=t=in:st={boundary}:d={length}:enable='between(t,{boundary},{_seconds(hook_boundary_ms + duration)})'[outa]"
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
                audio_metadata=audio_metadata,
            )
        )
        command.append(output_url)
        return tuple(command)


__all__ = [
    "AudioFade",
    "AudioOutputMetadata",
    "RenderCommandBuilder",
    "RenderEncoding",
    "SubtitleMode",
    "VideoOutputMetadata",
]
