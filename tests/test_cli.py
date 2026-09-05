import unittest
from contextlib import redirect_stdout
from io import StringIO

from minicut.cli import main, run_cli
from minicut.errors import UserInputError


class CommandLineHelpTest(unittest.TestCase):
    def test_help_exits_successfully_and_describes_the_product(self) -> None:
        output = StringIO()

        with redirect_stdout(output), self.assertRaises(SystemExit) as exit_context:
            main(["--help"])

        self.assertEqual(exit_context.exception.code, 0)
        self.assertIn("usage: minicut", output.getvalue())
        self.assertIn("rough-cutting", output.getvalue())


class CommandLineErrorTest(unittest.TestCase):
    @staticmethod
    def fail_with_expected_error() -> int:
        raise UserInputError("The media path is invalid.")

    def test_expected_error_hides_the_traceback_by_default(self) -> None:
        error_output = StringIO()

        exit_code = run_cli(
            self.fail_with_expected_error,
            error_stream=error_output,
        )

        self.assertEqual(exit_code, 1)
        self.assertEqual(error_output.getvalue(), "error: The media path is invalid.\n")
        self.assertNotIn("Traceback", error_output.getvalue())

    def test_debug_mode_retains_the_traceback(self) -> None:
        error_output = StringIO()

        exit_code = run_cli(
            self.fail_with_expected_error,
            debug=True,
            error_stream=error_output,
        )

        self.assertEqual(exit_code, 1)
        self.assertIn("Traceback (most recent call last)", error_output.getvalue())
        self.assertIn("UserInputError", error_output.getvalue())


if __name__ == "__main__":
    unittest.main()
