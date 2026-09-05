import unittest
from contextlib import redirect_stdout
from io import StringIO

from minicut.cli import main


class CommandLineHelpTest(unittest.TestCase):
    def test_help_exits_successfully_and_describes_the_product(self) -> None:
        output = StringIO()

        with redirect_stdout(output), self.assertRaises(SystemExit) as exit_context:
            main(["--help"])

        self.assertEqual(exit_context.exception.code, 0)
        self.assertIn("usage: minicut", output.getvalue())
        self.assertIn("rough-cutting", output.getvalue())


if __name__ == "__main__":
    unittest.main()
