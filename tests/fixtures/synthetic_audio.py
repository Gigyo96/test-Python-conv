"""Building audio with a known speech/silence structure.

Replay tests need recordings whose correct answer is knowable in advance. Rather
than checking in WAV files whose content is opaque in a diff, they are described
as a list of segments and generated on the spot.
"""

import wave
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from ielts_examiner.audio.frames import SAMPLE_RATE

Segment = tuple[str, int]
"""``("speech" | "silence", duration_ms)``."""

_SPEECH_AMPLITUDE = 0.25
"""Comfortably above EnergyVad's activation threshold."""

_SILENCE_AMPLITUDE = 0.001
"""Not digital silence: real rooms have a noise floor, and a detector that only
works against perfect zeros would pass here and fail in the field."""

_INT16_FULL_SCALE = 32767


def build_pcm(segments: Sequence[Segment], *, seed: int = 0) -> bytes:
    """Render segments to PCM16.

    Speech is rendered as band-limited noise rather than a tone: a pure sine has
    a constant RMS, which would hide any bug in the energy-slope calculation.

    Args:
        segments: the structure to render.
        seed: fixes the noise, so every run produces identical bytes.

    Returns:
        Little-endian mono PCM16 at 16 kHz.
    """
    rng = np.random.default_rng(seed)
    blocks = [
        rng.normal(0.0, amplitude, size=SAMPLE_RATE * duration_ms // 1000)
        for kind, duration_ms in segments
        for amplitude in (_SPEECH_AMPLITUDE if kind == "speech" else _SILENCE_AMPLITUDE,)
    ]
    signal = np.concatenate(blocks) if blocks else np.zeros(0)
    return (np.clip(signal, -1.0, 1.0) * _INT16_FULL_SCALE).astype("<i2").tobytes()


def write_wav(path: Path, segments: Sequence[Segment], *, seed: int = 0) -> Path:
    """Write segments to a session-format WAV file.

    Returns:
        ``path``, for chaining.
    """
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(build_pcm(segments, seed=seed))
    return path
