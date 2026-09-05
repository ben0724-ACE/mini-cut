import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

from minicut.errors import UserInputError
from minicut.media import MediaAsset
from minicut.project import ProjectManifest, ProjectRepository


def _read_manifest(path: Path) -> ProjectManifest:
    data = cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))
    return ProjectManifest.from_dict(data)


def _asset() -> MediaAsset:
    return MediaAsset(
        asset_id="asset-1",
        source_path="/media/example.mov",
        duration_ms=1_250,
        streams=(),
        content_fingerprint="fingerprint-1",
    )


class ObservingReplacer:
    def __init__(self) -> None:
        self.calls = 0
        self.source_manifest: ProjectManifest | None = None
        self.destination_manifest: ProjectManifest | None = None

    def __call__(self, source: Path, destination: Path) -> None:
        self.calls += 1
        self.source_manifest = _read_manifest(source)
        self.destination_manifest = _read_manifest(destination)
        source.replace(destination)


class ProjectRepositoryTest(unittest.TestCase):
    def test_create_and_read_manifest(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            project_directory = Path(temporary_directory) / "project"
            repository = ProjectRepository(project_directory)
            manifest = ProjectManifest(project_id="project-1", assets=(_asset(),))

            repository.create(manifest)

            self.assertEqual(repository.read(), manifest)
            self.assertEqual(
                repository.manifest_path, project_directory / "manifest.json"
            )
            self.assertEqual(
                list(project_directory.iterdir()), [repository.manifest_path]
            )

    def test_create_rejects_an_existing_manifest_without_overwriting_it(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            repository = ProjectRepository(Path(temporary_directory))
            original = ProjectManifest(project_id="original")
            repository.create(original)

            with self.assertRaisesRegex(UserInputError, "already exists"):
                repository.create(ProjectManifest(project_id="replacement"))

            self.assertEqual(repository.read(), original)

    def test_update_publishes_a_complete_manifest_with_one_replace(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            project_directory = Path(temporary_directory)
            original = ProjectManifest(project_id="project-1")
            updated = ProjectManifest(project_id="project-1", assets=(_asset(),))
            ProjectRepository(project_directory).create(original)
            replacer = ObservingReplacer()
            repository = ProjectRepository(project_directory, replace_file=replacer)

            repository.update(updated)

            self.assertEqual(replacer.calls, 1)
            self.assertEqual(replacer.destination_manifest, original)
            self.assertEqual(replacer.source_manifest, updated)
            self.assertEqual(repository.read(), updated)

    def test_read_and_update_reject_a_missing_manifest(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            repository = ProjectRepository(Path(temporary_directory))

            with self.assertRaisesRegex(UserInputError, "does not exist"):
                repository.read()
            with self.assertRaisesRegex(UserInputError, "does not exist"):
                repository.update(ProjectManifest(project_id="project-1"))


if __name__ == "__main__":
    unittest.main()
