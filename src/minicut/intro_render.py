"""Local still composition and a fixed synthesized music motif for intro cards."""

import wave
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from minicut.cover_design import extract_frame
from minicut.errors import UserInputError
from minicut.ffmpeg_paths import ffmpeg_file
from minicut.intro import IntroSettings
from minicut.render_command import VideoOutputMetadata
from minicut.renderer import FfmpegRenderer
from minicut.subtitle_font import SubtitleFont
from minicut.transcription_task import CancellationToken


def wrap_intro_text(
    text: str, font: ImageFont.FreeTypeFont, width: int, *, balanced: bool = False
) -> list[str]:
    def wrap(paragraph: str, limit: int) -> list[str]:
        result: list[str] = []
        line = ""
        for character in paragraph:
            if line and font.getlength(line + character) > limit:
                split = len(line)
                if character in "，。！？；：、）】》」』…,.!?;:%" and split > 1:
                    split -= 1
                while split > 1 and line[split - 1] in "（【《「『“‘":
                    split -= 1
                result.append(line[:split])
                line = line[split:]
            line += character
        return [*result, line]

    lines: list[str] = []
    for paragraph in text.splitlines():
        wrapped = wrap(paragraph, width)
        if balanced and len(wrapped) > 1:
            # Keep the same line count while finding a more even distribution.
            # This avoids a lone final character without changing any wording.
            low, high = 1, width
            while low < high:
                middle = (low + high) // 2
                if len(wrap(paragraph, middle)) > len(wrapped):
                    low = middle + 1
                else:
                    high = middle
            wrapped = wrap(paragraph, low)
        lines.extend(wrapped)
    return lines


def compose_intro(
    frame: Path,
    destination: Path,
    settings: IntroSettings,
    metadata: VideoOutputMetadata,
    font: SubtitleFont,
    *,
    title_path: Path | None = None,
    text_path: Path | None = None,
) -> None:
    width, height = metadata.width, metadata.height
    with Image.open(frame) as original:
        image = ImageOps.fit(original.convert("RGB"), (width, height))
    image = image.filter(ImageFilter.GaussianBlur(max(2, min(width, height) / 30)))
    image = ImageEnhance.Brightness(image).enhance(0.38)
    available_width, available_height = round(width * 0.82), round(height * 0.72)
    short_edge = min(width, height)
    title_size = max(12, round(short_edge * 0.072))
    body_size = max(9, round(short_edge * 0.039))
    gap = round(short_edge * 0.055) if settings.text.strip() else 0
    while True:
        title_font = ImageFont.truetype(str(font.path), title_size, index=font.index)
        body_font = ImageFont.truetype(str(font.path), body_size, index=font.index)
        title_lines = wrap_intro_text(
            settings.title.strip(), title_font, available_width, balanced=True
        )
        body_lines = wrap_intro_text(
            settings.text.strip(),
            body_font,
            available_width,
            balanced=settings.motion_style == "rise",
        )
        title_height, body_height = round(title_size * 1.5), round(body_size * 1.6)
        total = len(title_lines) * title_height + gap + len(body_lines) * body_height
        if total <= available_height:
            break
        if title_size <= max(9, round(short_edge * 0.032)):
            raise UserInputError("导读文字过多，当前画幅无法清晰排版，请精简标题或介绍")
        title_size -= 1
        body_size = max(8, round(title_size * 0.55))
    y = (height - total) / 2
    title_layer = Image.new("RGBA", (width, height))
    text_layer = Image.new("RGBA", (width, height))
    for lines, face, line_height, color in (
        (title_lines, title_font, title_height, "#ffffff"),
        (body_lines, body_font, body_height, "#e4e8ee"),
    ):
        draw = ImageDraw.Draw(title_layer if face is title_font else text_layer)
        for line in lines:
            draw.text(
                (width / 2, y),
                line,
                font=face,
                fill=color,
                anchor="mt",
                stroke_width=max(0, round(short_edge / 1000)),
                stroke_fill="#10151c",
            )
            y += line_height
        if face is title_font:
            y += gap
    if title_path is not None:
        title_layer.save(title_path, format="PNG")
    else:
        image.paste(title_layer, (0, 0), title_layer)
    if text_path is not None:
        text_layer.save(text_path, format="PNG")
    else:
        image.paste(text_layer, (0, 0), text_layer)
    image.save(destination, format="PNG")


def write_intro_music(
    destination: Path,
    duration_ms: int,
    enabled: bool,
    token: CancellationToken,
    version: int = 1,
    custom_audio: Path | None = None,
) -> None:
    """Trim the local score or loop an uploaded track on an exact sample clock.

    Audio is 48 kHz stereo PCM. Its duration is exact; the motif ends with a fade
    before any original speech begins. Disabled music produces digital silence.
    """
    del version  # Persisted legacy values now use the single built-in score.
    if not enabled:
        with wave.open(str(destination), "wb") as stream:
            stream.setnchannels(2)
            stream.setsampwidth(2)
            stream.setframerate(48000)
            stream.writeframes(bytes(duration_ms * 48 * 4))
        return
    duration = duration_ms / 1000
    score = custom_audio or Path(__file__).parent / "assets/intro-studio.ogg"
    FfmpegRenderer().render_to_path(
        (
            "ffmpeg",
            "-nostdin",
            "-y",
            *(("-stream_loop", "-1") if custom_audio else ()),
            "-i",
            ffmpeg_file(score),
            "-af",
            f"aresample=48000,asetpts=N/SR/TB,atrim=end_sample={duration_ms * 48},afade=t=in:d=0.04,afade=t=out:st={max(0, duration - 0.55):.3f}:d=0.55",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-c:a",
            "pcm_s16le",
            ffmpeg_file(destination),
        ),
        destination,
        timeout_seconds=30,
        cancellation=token,
    )


def prepare_intro(
    source: Path,
    frame_ms: int,
    directory: Path,
    settings: IntroSettings,
    metadata: VideoOutputMetadata,
    font: SubtitleFont,
    token: CancellationToken,
    custom_audio: Path | None = None,
) -> tuple[Path, Path, Path | None, Path | None]:
    frame, card, music = (
        directory / name for name in ("frame.png", "intro.png", "intro.wav")
    )
    token.raise_if_cancelled()
    extract_frame(source, frame, frame_ms, token)
    title = directory / "intro-title.png" if settings.motion else None
    text = (
        directory / "intro-text.png"
        if settings.motion and settings.text.strip()
        else None
    )
    compose_intro(
        frame, card, settings, metadata, font, title_path=title, text_path=text
    )
    write_intro_music(
        music,
        settings.duration_ms,
        settings.music,
        token,
        settings.music_version,
        custom_audio,
    )
    return card, music, title, text
