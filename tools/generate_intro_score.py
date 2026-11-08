"""Compose the bundled original intro score without models or external samples.

Run with the project's Python environment. FFmpeg encodes the final Ogg asset;
the intermediate 48 kHz stereo PCM lives in a temporary directory.
"""

import math
import random
import sys
import wave
from array import array
from pathlib import Path
from tempfile import TemporaryDirectory

from minicut.ffmpeg_paths import ffmpeg_file
from minicut.renderer import FfmpegRenderer

RATE = 48000
DURATION = 16


def compose(destination: Path) -> None:
    total = RATE * DURATION
    left = array("f", [0.0]) * total
    right = array("f", [0.0]) * total
    rng = random.Random(20261106)

    def tone(
        start: float, length: float, midi: int, gain: float, pan: float, kind: str
    ) -> None:
        frequency = 440 * 2 ** ((midi - 69) / 12)
        first = round(start * RATE)
        count = min(round(length * RATE), total - first)
        lg, rg = math.sqrt((1 - pan) / 2), math.sqrt((1 + pan) / 2)
        for index in range(count):
            t = index / RATE
            phase = 2 * math.pi * frequency * t
            if kind == "pad":
                envelope = min(1, t / 0.7, max(0, (length - t) / 1.1))
                envelope = envelope * envelope * (3 - 2 * envelope)
                signal = (
                    math.sin(phase)
                    + 0.35 * math.sin(phase * 1.002)
                    + 0.12 * math.sin(phase * 2)
                ) / 1.47
            elif kind == "bell":
                envelope = (
                    min(1, t / 0.008)
                    * math.exp(-t * 3.2)
                    * min(1, max(0, (length - t) / 0.1))
                )
                signal = math.sin(
                    phase + 1.8 * math.exp(-t * 8) * math.sin(phase * 2)
                ) + 0.15 * math.sin(phase * 3)
            else:
                envelope = min(1, t / 0.04, max(0, (length - t) / 0.4))
                signal = math.sin(phase) + 0.13 * math.sin(phase * 2)
            value = signal * envelope * gain
            left[first + index] += value * lg
            right[first + index] += value * rg

    # Four evolving extended chords, with a slow stereo pad and rounded bass.
    chords = (
        (48, 55, 59, 62, 64),
        (45, 52, 55, 59, 60),
        (41, 48, 52, 55, 57),
        (43, 50, 55, 57, 62),
    )
    for chord_index, chord in enumerate(chords):
        start = chord_index * 3.75
        for note_index, note in enumerate(chord):
            tone(start, 4.6, note + 12, 0.026, (note_index - 2) * 0.28, "pad")
        tone(start, 3.7, chord[0] - 12, 0.075, 0, "bass")

    # Sparse glass/electric-key melody; the tail of one note overlaps the next.
    melody = (
        76,
        79,
        83,
        79,
        74,
        79,
        72,
        76,
        79,
        76,
        71,
        76,
        69,
        72,
        76,
        72,
        67,
        72,
        71,
        74,
        79,
        74,
        69,
        74,
    )
    for index, note in enumerate(melody):
        tone(
            0.18 + index * 0.625,
            1.3,
            note,
            0.055 if index % 3 == 0 else 0.034,
            0.38 * math.sin(index * 1.7),
            "bell",
        )

    # Short rounded pulses, air at the text entrances, and quiet brushed ticks.
    for beat in range(24):
        start = round((0.15 + beat * 0.625) * RATE)
        for index in range(min(round(0.16 * RATE), total - start)):
            t = index / RATE
            thump = (
                0.04
                * math.sin(2 * math.pi * (48 * t + 4.8 * (1 - math.exp(-t * 22))))
                * math.exp(-t * 25)
            )
            if beat % 3 == 0:
                left[start + index] += thump
                right[start + index] += thump
        if beat % 3 == 2:
            previous = 0.0
            for index in range(min(round(0.075 * RATE), total - start)):
                noise = rng.uniform(-1, 1)
                tick = (noise - previous) * 0.013 * math.exp(-index / (RATE * 0.018))
                previous = noise
                left[start + index] += tick * 0.6
                right[start + index] += tick
    for second, gain, length in (
        (0.02, 0.025, 0.55),
        (0.28, 0.014, 0.45),
        (14.5, 0.018, 0.8),
    ):
        first = round(second * RATE)
        filtered = 0.0
        for index in range(min(round(length * RATE), total - first)):
            filtered += 0.09 * (rng.uniform(-1, 1) - filtered)
            value = filtered * gain * math.sin(math.pi * index / (length * RATE)) ** 2
            left[first + index] += value
            right[first + index] += value * 0.8

    # A restrained stereo room: cross-channel taps, without extending the card.
    wet_left, wet_right = array("f", left), array("f", right)
    for seconds, level in ((0.113, 0.17), (0.197, 0.12), (0.307, 0.08)):
        delay = round(seconds * RATE)
        for index in range(delay, total):
            wet_left[index] += right[index - delay] * level
            wet_right[index] += left[index - delay] * level
    peak = max(
        max(abs(value) for value in wet_left), max(abs(value) for value in wet_right)
    )
    pcm = array("h")
    for index in range(total):
        fade = min(1, index / (RATE * 0.04), (total - 1 - index) / (RATE * 0.8))
        for channel in (wet_left, wet_right):
            pcm.append(
                round(math.tanh(channel[index] / max(0.001, peak) * 0.6) * fade * 32767)
            )
    if sys.byteorder != "little":
        pcm.byteswap()
    with wave.open(str(destination), "wb") as stream:
        stream.setnchannels(2)
        stream.setsampwidth(2)
        stream.setframerate(RATE)
        stream.writeframes(pcm.tobytes())


def main() -> None:
    destination = (
        Path(__file__).resolve().parents[1] / "src/minicut/assets/intro-studio.ogg"
    )
    with TemporaryDirectory(prefix="minicut-score-") as directory:
        source = Path(directory) / "score.wav"
        compose(source)
        FfmpegRenderer().render_to_path(
            (
                "ffmpeg",
                "-nostdin",
                "-y",
                "-i",
                ffmpeg_file(source),
                "-af",
                "loudnorm=I=-22:TP=-5:LRA=7",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-c:a",
                "libvorbis",
                "-q:a",
                "5",
                ffmpeg_file(destination),
            ),
            destination,
            timeout_seconds=60,
        )
    print(destination)


if __name__ == "__main__":
    main()
