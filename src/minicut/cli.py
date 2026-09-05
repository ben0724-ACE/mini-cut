"""Command-line entry point for MiniCut."""

import argparse
from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """Parse command-line arguments and return a process exit status."""
    parser = argparse.ArgumentParser(
        prog="minicut",
        description="Local-first AI-assisted rough-cutting for spoken videos.",
    )
    parser.parse_args(argv)
    return 0
