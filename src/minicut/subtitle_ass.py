"""Styled ASS subtitles for translated burned previews and exports."""

from minicut.errors import UserInputError
from minicut.output_plan import OutputPlan
from minicut.subtitle_font import SubtitleFont
from minicut.subtitle_layout import SubtitleGeometry
from minicut.subtitle_pages import SubtitlePage
from minicut.subtitle_style import SubtitleStyle


def _ass_color(color: str, opacity: int = 100) -> str:
    red, green, blue = color[1:3], color[3:5], color[5:7]
    alpha = round(255 * (100 - opacity) / 100)
    return f"&H{alpha:02X}{blue}{green}{red}".upper()


def _ass_time(milliseconds: int) -> str:
    centiseconds = round(milliseconds / 10)
    hours, remainder = divmod(centiseconds, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    seconds, hundredths = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{hundredths:02d}"


def _ass_text(text: str) -> str:
    return (
        text.replace("\\", r"\\")
        .replace("{", r"\{")
        .replace("}", r"\}")
        .replace("\n", r"\N")
    )


def render_translated_ass(
    pages: tuple[SubtitlePage, ...],
    width: int,
    height: int,
    font: SubtitleFont,
    plan: OutputPlan | None = None,
    *,
    translation_font: SubtitleFont | None = None,
) -> str:
    """Keep each language's first row fixed throughout the saved output."""
    layout = SubtitleGeometry.for_output(
        width,
        height,
        plan,
        font if font.path.is_file() else None,
        translation_font
        if translation_font and translation_font.path.is_file()
        else None,
    )
    saved_style = plan.subtitle_style if plan else None
    scale = SubtitleStyle.scale(width, height)
    outline = (
        saved_style.stroke_width * scale
        if saved_style
        else max(1, round(height * 0.004))
    )
    shadow = saved_style.shadow_width * scale if saved_style else 0
    bold = -1 if saved_style is None or saved_style.bold else 0
    outline_color = (
        _ass_color(saved_style.stroke_color) if saved_style else "&H00000000"
    )
    shadow_color = (
        _ass_color(saved_style.shadow_color, 50) if saved_style else "&H80000000"
    )
    side, bottom, gap = layout.side, layout.bottom, layout.gap
    center_x = layout.center_x
    sizes = {
        "SourceSmall": layout.source_small,
        "SourceLarge": layout.source_large,
        "TranslationSmall": layout.translation_small,
        "TranslationLarge": layout.translation_large,
    }
    bilingual = any(page.source and page.translation for page in pages)
    source_size = max(
        (
            layout.sizes(page.translation_language)[0]
            for page in pages
            if page.source and page.translation
        ),
        default=layout.source_large,
    )
    translated_size = max(
        (
            layout.sizes(page.translation_language)[1]
            for page in pages
            if page.translation
        ),
        default=layout.translation_large,
    )
    # Reserve two rows normally. Exceptional fast/long cues reserve extra rows
    # once for the entire output, and carry a listening-review warning.
    source_rows = max(
        2,
        max((page.source.count("\n") + 1 for page in pages if page.source), default=0),
    )
    translation_rows = max(
        2,
        max(
            (page.translation.count("\n") + 1 for page in pages if page.translation),
            default=0,
        ),
    )
    source_height = source_rows * layout.row_height(source_size)
    translation_height = translation_rows * layout.row_height(translated_size)
    if layout.translation_first and bilingual:
        source_y = height - bottom - source_height
        translated_y = source_y - gap - translation_height
    else:
        translated_y = height - bottom - translation_height
        source_y = (
            translated_y - gap - source_height
            if bilingual
            else height - bottom - source_height
        )
    if (bilingual and min(source_y, translated_y) < layout.effect_padding) or (
        not bilingual
        and (
            (any(p.translation for p in pages) and translated_y < layout.effect_padding)
            or (any(p.source for p in pages) and source_y < layout.effect_padding)
        )
    ):
        raise UserInputError(
            "字幕区域超出画布，请拆分长句、调小字号或减小距底部后重新生成预览。"
        )
    header = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
    ]
    for name, size, color in (
        ("SourceSmall", layout.source_small, "&H00F4F4F4"),
        ("SourceLarge", layout.source_large, "&H00FFFFFF"),
        ("TranslationSmall", layout.translation_small, "&H00F4F4F4"),
        ("TranslationLarge", layout.translation_large, "&H00FFFFFF"),
    ):
        if saved_style:
            color = _ass_color(saved_style.text_color)
        style_font = (
            translation_font or font if name.startswith("Translation") else font
        )
        header.append(
            f"Style: {name},{style_font.family},{size},{color},&H00FFFFFF,{outline_color},{shadow_color},{bold},0,0,0,100,100,0,0,1,{outline:g},{shadow:g},2,{side},{side},{bottom},1"
        )
    header.extend(
        (
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        )
    )

    def event(text: str, style: str, start: str, end: str, y: int) -> None:
        measure = layout.measure(
            sizes[style], translated=style.startswith("Translation")
        )
        for row, line in enumerate(text.splitlines()):
            if measure(line) > layout.available_width:
                raise UserInputError(
                    "字幕含过宽的不可拆分词，无法完整显示；请调整文字、字号或横向位置后重新生成预览。"
                )
            top = y + row * layout.row_height(sizes[style])
            if saved_style and saved_style.background_enabled and line.strip():
                padding = layout.effect_padding
                half_width = measure(line) / 2 + padding
                box_height = layout.row_height(sizes[style])
                box_color = _ass_color(
                    saved_style.background_color, saved_style.background_opacity
                )
                header.append(
                    f"Dialogue: 0,{start},{end},{style},,0,0,0,,"
                    f"{{\\an7\\pos({center_x - half_width:g},{top - padding})"
                    f"\\bord0\\shad0\\1c&H{box_color[4:]}&\\1a{box_color[:4]}&\\p1}}"
                    f"m 0 0 l {2 * half_width:g} 0 {2 * half_width:g} {box_height}"
                    f" 0 {box_height}{{\\p0}}"
                )
            header.append(
                f"Dialogue: {1 if saved_style else 0},{start},{end},{style},,0,0,0,,"
                f"{{\\an8\\pos({center_x},{top})}}{_ass_text(line)}"
            )

    for page in pages:
        start, end = _ass_time(page.start_ms), _ass_time(page.end_ms)
        if page.translation:
            is_chinese = page.translation_language == "zh"
            translated_style = "TranslationLarge" if is_chinese else "TranslationSmall"
            source_style = "SourceSmall" if is_chinese else "SourceLarge"
            if page.source:
                event(page.source, source_style, start, end, source_y)
            event(page.translation, translated_style, start, end, translated_y)
        elif page.source:
            style = (
                "SourceSmall"
                if bilingual and source_size == layout.source_small
                else "SourceLarge"
            )
            event(page.source, style, start, end, source_y)
    return "\n".join(header) + "\n"
