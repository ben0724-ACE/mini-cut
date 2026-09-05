import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from minicut.errors import UserInputError
from minicut.importer import import_media
from minicut.media import StreamInfo, StreamType
from minicut.probe import ProbeResult
from minicut.project import ProjectManifest, ProjectRepository


class RecordingProbe:
    def __init__(self) -> None:
        self.paths: list[Path] = []

    def __call__(self, source_path: str | Path) -> ProbeResult:
        self.paths.append(Path(source_path))
        return ProbeResult(
            duration_ms=1_250,
            streams=(
                StreamInfo(
                    index=0,
                    stream_type=StreamType.VIDEO,
                    codec_name="h264",
                ),
            ),
        )


class AssetIdSequence:
    def __init__(self, *asset_ids: str) -> None:
        self._asset_ids = iter(asset_ids)
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        return next(self._asset_ids)


class MediaImportTest(unittest.TestCase):
    def test_import_registers_metadata_without_modifying_or_copying_source(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source.mov"
            source_bytes = b"read-only source media bytes"
            source.write_bytes(source_bytes)
            project_directory = root / "project"
            repository = ProjectRepository(project_directory)
            repository.create(ProjectManifest(project_id="project-1"))
            probe = RecordingProbe()

            asset = import_media(
                repository,
                source,
                mime_type="video/quicktime",
                probe=probe,
                generate_asset_id=AssetIdSequence("asset-1"),
            )

            self.assertEqual(asset.asset_id, "asset-1")
            self.assertEqual(asset.source_path, str(source))
            self.assertEqual(asset.duration_ms, 1_250)
            self.assertEqual(asset.streams[0].codec_name, "h264")
            self.assertEqual(probe.paths, [source])
            self.assertEqual(source.read_bytes(), source_bytes)
            self.assertEqual(repository.read().assets, (asset,))
            self.assertEqual(
                list(project_directory.iterdir()), [repository.manifest_path]
            )

    def test_importing_the_same_content_twice_returns_one_registered_asset(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source.mov"
            source.write_bytes(b"same source media bytes")
            repository = ProjectRepository(root / "project")
            repository.create(ProjectManifest(project_id="project-1"))
            probe = RecordingProbe()
            asset_ids = AssetIdSequence("asset-1", "asset-2")

            first = import_media(
                repository,
                source,
                probe=probe,
                generate_asset_id=asset_ids,
            )
            second = import_media(
                repository,
                source,
                probe=probe,
                generate_asset_id=asset_ids,
            )

            self.assertEqual(second, first)
            self.assertEqual(repository.read().assets, (first,))
            self.assertEqual(asset_ids.calls, 2)

    def test_import_rejects_a_missing_media_file_before_probe(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository = ProjectRepository(root / "project")
            repository.create(ProjectManifest(project_id="project-1"))
            probe = RecordingProbe()

            with self.assertRaisesRegex(UserInputError, "does not exist"):
                import_media(repository, root / "missing.mov", probe=probe)

            self.assertEqual(probe.paths, [])

    def test_import_rejects_an_unsupported_extension_before_probe(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "notes.txt"
            source.write_text("not media", encoding="utf-8")
            repository = ProjectRepository(root / "project")
            repository.create(ProjectManifest(project_id="project-1"))
            probe = RecordingProbe()

            with self.assertRaisesRegex(UserInputError, "Unsupported media extension"):
                import_media(repository, source, probe=probe)

            self.assertEqual(probe.paths, [])


if __name__ == "__main__":
    unittest.main()
