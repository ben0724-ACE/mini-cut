"""Command-line entry point for MiniCut."""

import argparse
import sys
import traceback
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO, cast

from minicut.application import (
    InitProjectOperation,
    InitProjectRequest,
    InitProjectUseCase,
    TranscribeOperation,
    TranscribeProjectUseCase,
    TranscribeRequest,
)
from minicut.errors import MiniCutError


@dataclass(frozen=True, slots=True)
class CliServices:
    """Injectable application use cases available to CLI handlers."""

    init_project: InitProjectOperation
    transcribe: TranscribeOperation | None = None


def _default_services() -> CliServices:
    return CliServices(
        init_project=InitProjectUseCase(),
        transcribe=TranscribeProjectUseCase(),
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    services: CliServices | None = None,
    output_stream: TextIO | None = None,
    error_stream: TextIO | None = None,
) -> int:
    """Parse command-line arguments and return a process exit status."""
    parser = argparse.ArgumentParser(
        prog="minicut",
        description="Local-first AI-assisted rough-cutting for spoken videos.",
    )
    parser.add_argument("--debug", action="store_true")
    commands = parser.add_subparsers(dest="command")
    init_parser = commands.add_parser("init", help="Initialize a MiniCut project.")
    init_parser.add_argument("project_directory", type=Path)
    init_parser.add_argument("--project-id", required=True)
    transcribe_parser = commands.add_parser(
        "transcribe", help="Transcribe media into the project."
    )
    transcribe_parser.add_argument("project_directory", type=Path)
    transcribe_parser.add_argument("source_path", type=Path)
    transcribe_parser.add_argument(
        "--provider", choices=("mlx", "whisper"), required=True
    )
    transcribe_parser.add_argument("--model", required=True)
    transcribe_parser.add_argument("--language", default="zh")
    parsed = parser.parse_args(argv)
    if parsed.command is None:
        return 0

    active_services = services if services is not None else _default_services()
    stdout = sys.stdout if output_stream is None else output_stream

    def operation() -> int:
        if parsed.command == "init":
            request = InitProjectRequest(
                cast(Path, parsed.project_directory),
                cast(str, parsed.project_id),
            )
            result = active_services.init_project.execute(request)
            print(f"Initialized project {result.project_id}.", file=stdout)
            return 0
        if parsed.command == "transcribe":
            if active_services.transcribe is None:
                raise AssertionError("Transcribe service is not configured")
            result = active_services.transcribe.execute(
                TranscribeRequest(
                    cast(Path, parsed.project_directory),
                    cast(Path, parsed.source_path),
                    cast(str, parsed.provider),
                    cast(str, parsed.model),
                    cast(str, parsed.language),
                )
            )
            print(
                f"Transcribed {result.word_count} words for asset {result.asset_id}.",
                file=stdout,
            )
            return 0
        raise AssertionError(f"Unhandled CLI command: {parsed.command}")

    return run_cli(
        operation,
        debug=cast(bool, parsed.debug),
        error_stream=error_stream,
    )


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
