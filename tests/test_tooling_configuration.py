import tomllib
import unittest
from pathlib import Path
from typing import cast

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_project() -> dict[str, object]:
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as project_file:
        return tomllib.load(project_file)


def require_table(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise AssertionError(f"expected table, got {type(value).__name__}")
    return cast(dict[str, object], value)


def require_nested_table(root: dict[str, object], *keys: str) -> dict[str, object]:
    current = root
    for key in keys:
        current = require_table(current[key])
    return current


def require_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        raise AssertionError(f"expected list, got {type(value).__name__}")
    items = cast(list[object], value)
    if not all(isinstance(item, str) for item in items):
        raise AssertionError("expected every list item to be a string")
    return cast(list[str], items)


def require_string(value: object) -> str:
    if not isinstance(value, str):
        raise AssertionError(f"expected string, got {type(value).__name__}")
    return value


class ToolingConfigurationTest(unittest.TestCase):
    def test_development_group_contains_quality_tools(self) -> None:
        project = load_project()
        dependency_groups = require_nested_table(project, "dependency-groups")
        development = require_string_list(dependency_groups["dev"])
        requirement_names = {
            requirement.split(">=", maxsplit=1)[0] for requirement in development
        }
        self.assertEqual(requirement_names, {"pyright", "pytest", "ruff"})

    def test_pytest_uses_strict_project_configuration(self) -> None:
        project = load_project()
        pytest_config = require_nested_table(project, "tool", "pytest", "ini_options")
        addopts = require_string(pytest_config["addopts"])

        self.assertEqual(require_string_list(pytest_config["pythonpath"]), ["."])
        self.assertEqual(require_string_list(pytest_config["testpaths"]), ["tests"])
        self.assertIn("--strict-config", addopts)
        self.assertIn("--strict-markers", addopts)
        self.assertTrue(pytest_config["xfail_strict"])

    def test_ruff_targets_the_supported_python_version(self) -> None:
        project = load_project()
        ruff_config = require_nested_table(project, "tool", "ruff")
        lint_config = require_nested_table(project, "tool", "ruff", "lint")

        self.assertEqual(ruff_config["target-version"], "py311")
        self.assertEqual(
            set(require_string_list(lint_config["select"])),
            {"B", "E4", "E7", "E9", "F", "I", "UP"},
        )

    def test_pyright_checks_source_and_tests_in_strict_mode(self) -> None:
        project = load_project()
        pyright_config = require_nested_table(project, "tool", "pyright")

        self.assertEqual(
            require_string_list(pyright_config["include"]),
            ["src", "tests", "tools"],
        )
        self.assertEqual(pyright_config["pythonVersion"], "3.11")
        self.assertEqual(pyright_config["typeCheckingMode"], "strict")


if __name__ == "__main__":
    unittest.main()
