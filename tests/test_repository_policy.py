from pathlib import Path
import subprocess
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def is_ignored(path: str) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--quiet", path],
        cwd=PROJECT_ROOT,
        check=False,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(f"git check-ignore failed with {result.returncode}")
    return result.returncode == 0


class RepositoryPolicyTest(unittest.TestCase):
    def test_root_readme_is_the_only_markdown_exception(self) -> None:
        self.assertFalse(is_ignored("README.md"))
        self.assertTrue(is_ignored("docs/PROJECT_PLAN.md"))
        self.assertTrue(is_ignored("notes.md"))

    def test_local_and_sensitive_artifacts_are_ignored(self) -> None:
        for path in (
            ".DS_Store",
            ".env",
            "outputs/render.mp4",
            "cache/model.bin",
            "runtime.log",
        ):
            with self.subTest(path=path):
                self.assertTrue(is_ignored(path))


if __name__ == "__main__":
    unittest.main()
