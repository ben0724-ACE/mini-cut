"""Local dictionary boundaries for Chinese subtitle wrapping and pagination."""

import logging
from collections.abc import Iterator
from functools import lru_cache
from importlib import import_module
from typing import Protocol, cast


class ChineseTokenizer(Protocol):
    def cut(self, sentence: str, HMM: bool = True) -> Iterator[str]: ...


@lru_cache(maxsize=1)
def _tokenizer() -> ChineseTokenizer:
    module = import_module("jieba")
    logging.getLogger("jieba").setLevel(logging.WARNING)
    return cast(ChineseTokenizer, module.Tokenizer())


def is_chinese(character: str) -> bool:
    return "\u3400" <= character <= "\u9fff"


@lru_cache(maxsize=2048)
def chinese_word_edges(text: str) -> frozenset[int]:
    if not any(is_chinese(character) for character in text):
        return frozenset()
    edges: set[int] = set()
    offset = 0
    # The packaged dictionary is enough here; disable new-word model inference.
    for token in _tokenizer().cut(text, HMM=False):
        offset += len(token)
        edges.add(offset)
    return frozenset(edges)
