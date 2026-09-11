import unittest
from dataclasses import dataclass

from minicut.audio_denoise import (
    AudioDenoiser,
    FfmpegAudioDenoiser,
    build_denoiser_registry,
    resolve_denoiser,
)


@dataclass(frozen=True)
class CustomDenoiser:
    provider_id: str = "custom"

    def ffmpeg_filter(self) -> str:
        return "anlmdn=s=0.001"


class AudioDenoiserPluginTest(unittest.TestCase):
    def test_resolves_builtin_and_injected_denoisers_by_id(self) -> None:
        custom: AudioDenoiser = CustomDenoiser()
        registry = build_denoiser_registry((custom,))

        self.assertEqual(resolve_denoiser("none", registry), None)
        builtin = resolve_denoiser("afftdn", registry)
        assert builtin is not None
        self.assertEqual(builtin.provider_id, "afftdn")
        self.assertIs(resolve_denoiser("custom", registry), custom)
        self.assertEqual(custom.ffmpeg_filter(), "anlmdn=s=0.001")

    def test_rejects_duplicate_unknown_or_invalid_providers(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate"):
            build_denoiser_registry((CustomDenoiser(), CustomDenoiser()))
        with self.assertRaisesRegex(ValueError, "unknown"):
            resolve_denoiser("missing", build_denoiser_registry())
        with self.assertRaises(ValueError):
            FfmpegAudioDenoiser("bad id", "afftdn")
        with self.assertRaises(ValueError):
            FfmpegAudioDenoiser("valid", " ")


if __name__ == "__main__":
    unittest.main()
