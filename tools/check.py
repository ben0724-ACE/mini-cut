"""Run the complete local quality gate."""

import shlex
import subprocess
import sys
from collections.abc import Callable, Sequence

Command = tuple[str, ...]
Runner = Callable[[Command], int]

QUALITY_COMMANDS: tuple[Command, ...] = (
    (sys.executable, "-m", "pytest"),
    (sys.executable, "-m", "ruff", "check", "."),
    (sys.executable, "-m", "ruff", "format", "--check", "."),
    (sys.executable, "-m", "pyright"),
)


def run_command(command: Command) -> int:
    """Run one quality command and return its exit status."""
    print(f"$ {shlex.join(command)}", flush=True)
    return subprocess.run(command, check=False).returncode


def run_quality_checks(
    commands: Sequence[Command] = QUALITY_COMMANDS,
    runner: Runner = run_command,
) -> int:
    """Run quality commands in order and stop after the first failure."""
    for command in commands:
        return_code = runner(command)
        if return_code != 0:
            return return_code
    return 0


def main() -> int:
    """Run the repository quality gate."""
    return run_quality_checks()


if __name__ == "__main__":
    raise SystemExit(main())
