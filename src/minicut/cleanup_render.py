"""Bounded-memory rendering for a whole-source, chronological cleanup."""

import shutil
import time
from pathlib import Path

from minicut.application import TimelineRenderer
from minicut.errors import ProcessingError
from minicut.media import MediaAsset
from minicut.output_plan import OutputPlan, OutputRole
from minicut.render_command import AudioFade, RenderCommandBuilder, VideoOutputMetadata
from minicut.renderer import RenderTimeout
from minicut.timeline import Timeline
from minicut.transcription_task import CancellationToken


def can_stream_cleanup(plan: OutputPlan, timeline: Timeline) -> bool:
    return (
        plan.workflow == "speech_cleanup"
        and all(i.role is OutputRole.BODY for i in plan.items if not i.deleted)
        and timeline.clips[0].output_range.start_ms == 0
        and all(
            a.source_range.end_ms <= b.source_range.start_ms
            and a.output_range.end_ms == b.output_range.start_ms
            for a, b in zip(timeline.clips, timeline.clips[1:], strict=False)
        )
    )


def render_cleanup(
    timeline: Timeline,
    asset: MediaAsset,
    output: Path,
    metadata: VideoOutputMetadata,
    fade: AudioFade,
    denoise_filter: str | None,
    has_audio: bool,
    builder: RenderCommandBuilder,
    renderer: TimelineRenderer,
    timeout: float,
    cancellation: CancellationToken | None,
) -> None:
    token = cancellation or CancellationToken()
    started = time.monotonic()

    def render(command: tuple[str, ...], destination: Path) -> None:
        token.raise_if_cancelled()
        remaining = timeout - (time.monotonic() - started)
        if remaining <= 0:
            raise RenderTimeout("Rendering timed out.")
        renderer.render_to_path(
            command, destination, timeout_seconds=remaining, cancellation=token
        )

    video = output.with_name("cleanup-video.mp4") if has_audio else output
    render(builder.build_cleanup_video(timeline, asset, str(video), metadata), video)
    if not has_audio:
        return
    audio = output.with_name("cleanup-audio.pcm")
    chunk = output.with_name("cleanup-chunk.pcm")
    with audio.open("wb") as combined:
        for clip in timeline.clips:
            render(
                builder.build_cleanup_audio(
                    asset,
                    clip.source_range.start_ms,
                    clip.source_range.duration_ms,
                    str(chunk),
                    fade,
                    denoise_filter,
                ),
                chunk,
            )
            # Stereo signed 16-bit PCM at 48 kHz: each millisecond is 192 bytes.
            expected = clip.source_range.duration_ms * 192
            if chunk.stat().st_size != expected:
                raise ProcessingError(
                    "清理音频长度与保存的剪辑范围不一致，未发布成片。"
                )
            with chunk.open("rb") as samples:
                shutil.copyfileobj(samples, combined, length=64 * 1024)
            chunk.unlink()
            token.raise_if_cancelled()
    render(builder.build_cleanup_mux(video, audio, output), output)
