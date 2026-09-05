import unittest

from tools.check import QUALITY_COMMANDS, Command, run_quality_checks


class RecordingRunner:
    def __init__(self, return_codes: tuple[int, ...]) -> None:
        self._return_codes = iter(return_codes)
        self.commands: list[Command] = []

    def __call__(self, command: Command) -> int:
        self.commands.append(command)
        return next(self._return_codes)


class QualityCommandTest(unittest.TestCase):
    def test_default_plan_contains_every_quality_gate_in_order(self) -> None:
        modules = tuple(command[2] for command in QUALITY_COMMANDS)

        self.assertEqual(modules, ("pytest", "ruff", "ruff", "pyright"))
        self.assertEqual(QUALITY_COMMANDS[1][-2:], ("check", "."))
        self.assertEqual(QUALITY_COMMANDS[2][-3:], ("format", "--check", "."))

    def test_success_runs_every_quality_gate(self) -> None:
        runner = RecordingRunner((0, 0, 0, 0))

        return_code = run_quality_checks(runner=runner)

        self.assertEqual(return_code, 0)
        self.assertEqual(runner.commands, list(QUALITY_COMMANDS))

    def test_failure_stops_at_the_first_failed_gate(self) -> None:
        runner = RecordingRunner((0, 7))

        return_code = run_quality_checks(runner=runner)

        self.assertEqual(return_code, 7)
        self.assertEqual(runner.commands, list(QUALITY_COMMANDS[:2]))

    def test_empty_plan_succeeds_without_running_a_command(self) -> None:
        runner = RecordingRunner(())

        return_code = run_quality_checks(commands=(), runner=runner)

        self.assertEqual(return_code, 0)
        self.assertEqual(runner.commands, [])


if __name__ == "__main__":
    unittest.main()
