"""Command-line entry point for MiniCut."""

import argparse
import sys
import traceback
from collections.abc import Callable, Sequence
from typing import TextIO

from minicut.errors import MiniCutError


def main(argv: Sequence[str] | None = None) -> int:
    """Parse command-line arguments and return a process exit status."""
    parser = argparse.ArgumentParser(
        prog="minicut",
        description="Local-first AI-assisted rough-cutting for spoken videos.",
    )
    parser.parse_args(argv)
    return 0


def run_cli(
    operation: Callable[[], int],
    *,
    debug: bool = False,
    error_stream: TextIO | None = None,
) -> int:
    """Run a CLI operation and present expected failures safely."""
    stream = sys.stderr if error_stream is None else error_stream
    try:
        return operation()
    except MiniCutError as error:
        if debug:
            traceback.print_exception(error, file=stream)
        else:
            print(f"error: {error}", file=stream)
        return 1
