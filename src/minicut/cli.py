"""Command-line entry point for MiniCut."""

import argparse
import json
import signal
import sys
import traceback
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import FrameType
from typing import TextIO, cast

from minicut.application import (
    EditOperation,
    EditProgressEvent,
    EditProjectUseCase,
    EditRequest,
    InitProjectOperation,
    InitProjectRequest,
    InitProjectUseCase,
    InspectOperation,
    InspectProjectUseCase,
    InspectRequest,
    PlanOperation,
    PlanProjectUseCase,
    PlanRequest,
    RenderOperation,
    RenderProjectUseCase,
    RenderRequest,
    TranscribeOperation,
    TranscribeProjectUseCase,
    TranscribeRequest,
)
from minicut.edit_plan import EditIntensity
from minicut.errors import MiniCutError
from minicut.transcription_task import CancellationToken


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def _format_edit_progress(event: EditProgressEvent) -> str:
    detail = "reused" if event.reused else event.status
    duration = (
        ""
        if event.estimated_duration_ms is None
        else f"; estimated output {event.estimated_duration_ms} ms"
    )
    return f"[{event.stage}] {detail}{duration}"


@dataclass(frozen=True, slots=True)
class CliServices:
    """Injectable application use cases available to CLI handlers."""

    init_project: InitProjectOperation
    transcribe: TranscribeOperation | None = None
    plan: PlanOperation | None = None
    render: RenderOperation | None = None
    inspect: InspectOperation | None = None
    edit: EditOperation | None = None


def _default_services() -> CliServices:
    return CliServices(
        init_project=InitProjectUseCase(),
        transcribe=TranscribeProjectUseCase(),
        plan=PlanProjectUseCase(),
        render=RenderProjectUseCase(),
        inspect=InspectProjectUseCase(),
        edit=EditProjectUseCase(),
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
    plan_parser = commands.add_parser("plan", help="Build an edit plan.")
    plan_parser.add_argument("project_directory", type=Path)
    plan_parser.add_argument("--asset-id", required=True)
    plan_parser.add_argument("--target-ms", required=True, type=_positive_int)
    plan_parser.add_argument(
        "--intensity",
        choices=tuple(intensity.value for intensity in EditIntensity),
        default=EditIntensity.BALANCED.value,
    )
    plan_parser.add_argument("--style", default="concise")
    plan_parser.add_argument("--planner", choices=("rule", "deepseek"), default="rule")
    render_parser = commands.add_parser("render", help="Render video and subtitles.")
    render_parser.add_argument("project_directory", type=Path)
    render_parser.add_argument("--asset-id", required=True)
    render_parser.add_argument("--output", required=True, type=Path)
    render_parser.add_argument("--timeout", type=_positive_int, default=600)
    inspect_parser = commands.add_parser("inspect", help="Inspect project artifacts.")
    inspect_parser.add_argument("project_directory", type=Path)
    inspect_parser.add_argument("--asset-id")
    edit_parser = commands.add_parser("edit", help="Run the complete edit workflow.")
    edit_parser.add_argument("project_directory", type=Path)
    edit_parser.add_argument("source_path", type=Path)
    edit_parser.add_argument("--provider", choices=("mlx", "whisper"), required=True)
    edit_parser.add_argument("--model", required=True)
    edit_parser.add_argument("--language", default="zh")
    edit_parser.add_argument("--target-ms", required=True, type=_positive_int)
    edit_parser.add_argument(
        "--intensity",
        choices=tuple(intensity.value for intensity in EditIntensity),
        default=EditIntensity.BALANCED.value,
    )
    edit_parser.add_argument("--style", default="concise")
    edit_parser.add_argument("--planner", choices=("rule", "deepseek"), default="rule")
    edit_parser.add_argument("--output", required=True, type=Path)
    edit_parser.add_argument("--timeout", type=_positive_int, default=600)
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
        if parsed.command == "edit":
            if active_services.edit is None:
                raise AssertionError("Edit service is not configured")
            cancellation = CancellationToken()

            def cancel_edit(signal_number: int, frame: FrameType | None) -> None:
                del signal_number, frame
                cancellation.cancel()

            previous_handler = signal.signal(signal.SIGINT, cancel_edit)
            try:
                result = active_services.edit.execute(
                    EditRequest(
                        cast(Path, parsed.project_directory),
                        cast(Path, parsed.source_path),
                        cast(str, parsed.provider),
                        cast(str, parsed.model),
                        cast(str, parsed.language),
                        cast(int, parsed.target_ms),
                        EditIntensity(cast(str, parsed.intensity)),
                        cast(str, parsed.style),
                        cast(str, parsed.planner),
                        cast(Path, parsed.output),
                        float(cast(int, parsed.timeout)),
                        lambda event: print(_format_edit_progress(event), file=stdout),
                        cancellation,
                    )
                )
            finally:
                signal.signal(signal.SIGINT, previous_handler)
            print(
                f"Edited asset {result.asset_id} to {result.output_path}.", file=stdout
            )
            return 0
        if parsed.command == "inspect":
            if active_services.inspect is None:
                raise AssertionError("Inspect service is not configured")
            result = active_services.inspect.execute(
                InspectRequest(
                    cast(Path, parsed.project_directory),
                    cast(str | None, parsed.asset_id),
                )
            )
            print(json.dumps(result.to_dict(), ensure_ascii=False), file=stdout)
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
        if parsed.command == "render":
            if active_services.render is None:
                raise AssertionError("Render service is not configured")
            result = active_services.render.execute(
                RenderRequest(
                    cast(Path, parsed.project_directory),
                    cast(str, parsed.asset_id),
                    cast(Path, parsed.output),
                    float(cast(int, parsed.timeout)),
                )
            )
            print(
                f"Rendered {result.duration_ms} ms to {result.output_path}.",
                file=stdout,
            )
            return 0
        if parsed.command == "plan":
            if active_services.plan is None:
                raise AssertionError("Plan service is not configured")
            result = active_services.plan.execute(
                PlanRequest(
                    cast(Path, parsed.project_directory),
                    cast(str, parsed.asset_id),
                    cast(int, parsed.target_ms),
                    EditIntensity(cast(str, parsed.intensity)),
                    cast(str, parsed.style),
                    cast(str, parsed.planner),
                )
            )
            print(
                f"Planned {result.kept_segments} kept and "
                f"{result.deleted_segments} deleted segments.",
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
