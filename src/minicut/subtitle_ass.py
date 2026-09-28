"""Styled ASS subtitles for translated burned previews and exports."""

from minicut.output_plan import OutputPlan
from minicut.subtitle_font import SubtitleFont
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
    """Place each language independently inside the bottom safe area."""
    if width <= 0 or height <= 0:
        raise ValueError("subtitle dimensions must be positive")
    small = max(13, round(height * (0.042 if width >= height else 0.033)))
    large = max(16, round(height * (0.055 if width >= height else 0.041)))
    outline = max(1, round(height * 0.004))
    side = round(width * 0.07)
    bottom = round(height * (0.105 if width >= height else 0.095))
    gap = round(height * 0.022)
    source_scale = plan.subtitle_source_scale if plan else 1.0
    translation_scale = plan.subtitle_translation_scale if plan else 1.0
    center_x = round(width * (plan.subtitle_horizontal_percent if plan else 50) / 100)
    bottom = (
        round(height * (plan.subtitle_bottom_percent if plan else 10) / 100)
        if plan
        else bottom
    )
    translation_first = plan is not None and plan.subtitle_order == "translation_first"
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
        ("SourceSmall", round(small * source_scale), "&H00F4F4F4"),
        ("SourceLarge", round(large * source_scale), "&H00FFFFFF"),
        ("TranslationSmall", round(small * translation_scale), "&H00F4F4F4"),
        ("TranslationLarge", round(large * translation_scale), "&H00FFFFFF"),
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
    for page in pages:
        start, end = _ass_time(page.start_ms), _ass_time(page.end_ms)
        if page.translation:
            is_chinese = page.translation_language == "zh"
            translated_style = "TranslationLarge" if is_chinese else "TranslationSmall"
            source_style = "SourceSmall" if is_chinese else "SourceLarge"
            translated_size = round(
                (large if is_chinese else small) * translation_scale
            )
            source_size = round((small if is_chinese else large) * source_scale)
            translated_lines = page.translation.count("\n") + 1
            source_lines = page.source.count("\n") + 1 if page.source else 0
            if translation_first and page.source:
                source_y = height - bottom
                translated_y = source_y - round(source_lines * source_size * 1.25) - gap
            else:
                translated_y = height - bottom
                source_y = (
                    translated_y
                    - round(translated_lines * translated_size * 1.25)
                    - gap
                )
            if page.source:
                header.append(
                    f"Dialogue: 0,{start},{end},{source_style},,0,0,0,,"
                    f"{{\\an2\\pos({center_x},{source_y})}}{_ass_text(page.source)}"
                )
            header.append(
                f"Dialogue: 0,{start},{end},{translated_style},,0,0,0,,"
                f"{{\\an2\\pos({center_x},{translated_y})}}{_ass_text(page.translation)}"
            )
        elif page.source:
            header.append(
                f"Dialogue: 0,{start},{end},SourceLarge,,0,0,0,,"
                f"{{\\an2\\pos({center_x},{height - bottom})}}{_ass_text(page.source)}"
            )
    return "\n".join(header) + "\n"
