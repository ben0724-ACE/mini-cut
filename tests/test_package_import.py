from pathlib import Path
import tomllib
import unittest

import minicut


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PackageImportTest(unittest.TestCase):
    def test_package_can_be_imported(self) -> None:
        self.assertEqual(minicut.__name__, "minicut")

    def test_build_backend_targets_the_import_package(self) -> None:
        with (PROJECT_ROOT / "pyproject.toml").open("rb") as project_file:
            project = tomllib.load(project_file)

        module_name = project["tool"]["uv"]["build-backend"]["module-name"]
        self.assertEqual(module_name, minicut.__name__)

    def test_project_declares_python_311_as_the_minimum(self) -> None:
        with (PROJECT_ROOT / "pyproject.toml").open("rb") as project_file:
            project = tomllib.load(project_file)

        self.assertEqual(project["project"]["requires-python"], ">=3.11")


if __name__ == "__main__":
    unittest.main()
