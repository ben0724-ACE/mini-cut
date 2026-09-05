"""MiniCut application package."""

from importlib.metadata import version
from typing import Final

__version__: Final = version("mini-cut")

__all__ = ["__version__"]
