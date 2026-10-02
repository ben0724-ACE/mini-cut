"""Styled ASS subtitles for translated burned previews and exports."""

from minicut.errors import UserInputError
from minicut.output_plan import OutputPlan
from minicut.subtitle_font import SubtitleFont
from minicut.subtitle_layout import SubtitleGeometry
from minicut.subtitle_pages import SubtitlePage


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
) -> str:
    """Keep each language's first row fixed throughout the saved output."""
    layout = SubtitleGeometry.for_output(
        width, height, plan, font if font.path.is_file() else None
    )
    outline = max(1, round(height * 0.004))
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
    if (bilingual and min(source_y, translated_y) < 0) or (
        not bilingual
        and (
            (any(p.translation for p in pages) and translated_y < 0)
            or (any(p.source for p in pages) and source_y < 0)
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
        header.append(
            f"Style: {name},{font.family},{size},{color},&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,{outline},0,2,{side},{side},{bottom},1"
        )
    header.extend(
        (
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        )
    )

    def event(text: str, style: str, start: str, end: str, y: int) -> None:
        measure = layout.measure(sizes[style])
        for row, line in enumerate(text.splitlines()):
            if measure(line) > layout.available_width:
                raise UserInputError(
                    "字幕含过宽的不可拆分词，无法完整显示；请调整文字、字号或横向位置后重新生成预览。"
                )
            header.append(
                f"Dialogue: 0,{start},{end},{style},,0,0,0,,"
                f"{{\\an8\\pos({center_x},{y + row * layout.row_height(sizes[style])})}}{_ass_text(line)}"
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
