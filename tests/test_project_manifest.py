import json
import unittest
from typing import cast

from minicut.media import MediaAsset, StreamInfo, StreamType
from minicut.project import MANIFEST_SCHEMA_VERSION, ProjectManifest


def _media_asset() -> MediaAsset:
    return MediaAsset(
        asset_id="asset-1",
        source_path="/media/example.mov",
        duration_ms=1_250,
        streams=(
            StreamInfo(index=0, stream_type=StreamType.VIDEO, codec_name="h264"),
            StreamInfo(index=1, stream_type=StreamType.AUDIO, codec_name="aac"),
        ),
        content_fingerprint="fingerprint-1",
    )


class ProjectManifestTest(unittest.TestCase):
    def test_manifest_round_trips_through_json(self) -> None:
        manifest = ProjectManifest(project_id="project-1", assets=(_media_asset(),))

        encoded = json.dumps(manifest.to_dict())
        decoded = cast(dict[str, object], json.loads(encoded))
        restored = ProjectManifest.from_dict(decoded)

        self.assertEqual(restored, manifest)
        self.assertEqual(restored.schema_version, MANIFEST_SCHEMA_VERSION)

    def test_manifest_rejects_blank_project_id(self) -> None:
        with self.assertRaisesRegex(ValueError, "project_id must not be blank"):
            ProjectManifest(project_id="  ")

    def test_manifest_rejects_unsupported_schema_version(self) -> None:
        data = ProjectManifest(project_id="project-1").to_dict()
        data["schema_version"] = MANIFEST_SCHEMA_VERSION + 1

        with self.assertRaisesRegex(ValueError, "Unsupported manifest schema version"):
            ProjectManifest.from_dict(data)


if __name__ == "__main__":
    unittest.main()
