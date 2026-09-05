import tomllib
import unittest
from importlib.metadata import version as distribution_version
from pathlib import Path

import minicut

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class VersionContractTest(unittest.TestCase):
    def test_public_version_is_a_nonempty_string(self) -> None:
        self.assertIsInstance(minicut.__version__, str)
        self.assertTrue(minicut.__version__)

    def test_public_version_matches_project_and_distribution_metadata(self) -> None:
        with (PROJECT_ROOT / "pyproject.toml").open("rb") as project_file:
            project_version = tomllib.load(project_file)["project"]["version"]

        self.assertEqual(minicut.__version__, project_version)
        self.assertEqual(minicut.__version__, distribution_version("mini-cut"))


if __name__ == "__main__":
    unittest.main()
