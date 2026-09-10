import shutil
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from minicut.application import (
    EditProjectUseCase,
    EditRequest,
    TranscribeProjectUseCase,
    TranscribeRequest,
)
from minicut.edit_plan import EditIntensity
from minicut.media import MediaAsset, StreamType
from minicut.probe import probe_media
from minicut.project import ProjectManifest, ProjectRepository
from minicut.subtitle import parse_srt
from minicut.transcript import Transcript, TranscriptSource, Utterance, Word


@unittest.skipUnless(
    shutil.which("ffmpeg") and shutil.which("ffprobe"),
    "ffmpeg and ffprobe are required",
)
class RealEditWorkflowTest(unittest.TestCase):
    def test_one_command_exports_media_and_reuses_complete_project(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            project_directory = root / "project"
            source = root / "source.mp4"
            output = root / "exports" / "edited.mp4"
            output.parent.mkdir()
            generated = subprocess.run(
                (
                    "ffmpeg",
                    "-v",
                    "error",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc=size=320x240:rate=25:duration=2",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=440:sample_rate=48000:duration=2",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-shortest",
                    str(source),
                ),
                capture_output=True,
                check=False,
            )
            self.assertEqual(generated.returncode, 0, generated.stderr.decode())
            ProjectRepository(project_directory).create(ProjectManifest("e2e"))
            transcription_calls = 0

            def transcriber(
                asset: MediaAsset, request: TranscribeRequest
            ) -> Transcript:
                nonlocal transcription_calls
                del request
                transcription_calls += 1
                return Transcript(
                    "transcript-e2e",
                    TranscriptSource(asset.asset_id, "mlx-whisper", "large-v3-turbo"),
                    "zh",
                    (
                        Word("w1", "第一段。", 100, 600),
                        Word("w2", "嗯", 1_000, 1_500),
                    ),
                    (
                        Utterance("u1", "第一段。", 100, 600, ("w1",)),
                        Utterance("u2", "嗯", 1_000, 1_500, ("w2",)),
                    ),
                )

            use_case = EditProjectUseCase(
                transcribe=TranscribeProjectUseCase(transcriber=transcriber)
            )
            request = EditRequest(
                project_directory,
                source,
                "mlx",
                "large-v3-turbo",
                "zh",
                1_000,
                EditIntensity.BALANCED,
                "concise",
                "rule",
                output,
                30,
            )

            first = use_case.execute(request)
            second = use_case.execute(request)

            self.assertEqual(first.reused_stages, ())
            self.assertEqual(second.reused_stages, ("transcribe", "plan", "render"))
            self.assertEqual(transcription_calls, 1)
            self.assertTrue(output.is_file())
            self.assertTrue(first.subtitle_path.is_file())
            self.assertTrue(parse_srt(first.subtitle_path.read_text(encoding="utf-8")))
            probed = probe_media(output)
            self.assertEqual(
                {stream.stream_type for stream in probed.streams},
                {StreamType.VIDEO, StreamType.AUDIO},
            )
            manifest = ProjectRepository(project_directory).read()
            asset_id = manifest.assets[0].asset_id
            for artifact in (
                project_directory / ".minicut/transcripts" / f"{asset_id}.json",
                project_directory / ".minicut/plans" / f"{asset_id}.json",
                project_directory / ".minicut/renders" / f"{asset_id}.json",
            ):
                self.assertTrue(artifact.is_file(), artifact)


if __name__ == "__main__":
    unittest.main()
