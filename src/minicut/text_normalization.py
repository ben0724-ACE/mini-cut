"""Deterministic text cleanup before semantic segmentation."""

import re
from dataclasses import dataclass
from enum import StrEnum
from importlib import import_module
from typing import Protocol, cast

from minicut.errors import ProcessingError

_PUNCTUATION_TRANSLATION = str.maketrans(
    {
        "﹐": "，",
        "︐": "，",
        "｡": "。",
        "﹒": "。",
        "︒": "。",
        "﹗": "！",
        "﹖": "？",
        "﹕": "：",
        "﹔": "；",
        "﹑": "、",
        "︑": "、",
    }
)
_CJK_PUNCTUATION = "，。！？；：、"
_OPENING_PUNCTUATION = "（【《「『“‘"
_CLOSING_PUNCTUATION = "）】》」』”’"


class ChineseScriptPolicy(StrEnum):
    """How normalized text handles traditional Chinese characters."""

    SIMPLIFIED = "simplified"
    PRESERVE = "preserve"


@dataclass(slots=True)
class TextNormalizationPolicy:
    """Text choices that must remain consistent across the pipeline."""

    chinese_script: ChineseScriptPolicy = ChineseScriptPolicy.SIMPLIFIED


class ChineseConverter(Protocol):
    """Subset of the OpenCC converter used by MiniCut."""

    def convert(self, text: str) -> str:
        """Convert Chinese text according to the configured script mapping."""
        ...


def _load_simplified_converter() -> ChineseConverter:
    try:
        module = import_module("opencc")
        factory = module.OpenCC
        return cast(ChineseConverter, factory("t2s"))
    except (AttributeError, ImportError, OSError, TypeError, ValueError) as error:
        raise ProcessingError("Chinese text conversion is not available") from error


def _normalize_spacing_and_punctuation(text: str) -> str:
    normalized = " ".join(text.split()).translate(_PUNCTUATION_TRANSLATION)
    normalized = re.sub(
        rf"\s*([{re.escape(_CJK_PUNCTUATION)}])\s*",
        r"\1",
        normalized,
    )
    normalized = re.sub(
        rf"([{re.escape(_OPENING_PUNCTUATION)}])\s+",
        r"\1",
        normalized,
    )
    return re.sub(
        rf"\s+([{re.escape(_CLOSING_PUNCTUATION)}])",
        r"\1",
        normalized,
    )


def normalize_text(
    text: str,
    *,
    policy: TextNormalizationPolicy | None = None,
    converter: ChineseConverter | None = None,
) -> str:
    """Normalize whitespace, punctuation variants, and Chinese script."""
    selected_policy = policy if policy is not None else TextNormalizationPolicy()
    normalized = _normalize_spacing_and_punctuation(text)
    if not normalized or selected_policy.chinese_script is ChineseScriptPolicy.PRESERVE:
        return normalized

    selected_converter = (
        converter if converter is not None else _load_simplified_converter()
    )
    try:
        return selected_converter.convert(normalized)
    except Exception as error:
        raise ProcessingError("Chinese text conversion failed") from error


__all__ = [
    "ChineseConverter",
    "ChineseScriptPolicy",
    "TextNormalizationPolicy",
    "normalize_text",
]
