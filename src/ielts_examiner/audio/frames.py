"""Fixed-size blocks of candidate audio.

One format is used everywhere between the browser and the recogniser: 16 kHz
mono PCM16, in 20 ms frames. Resampling happens once, in the browser's audio
worklet, so nothing downstream has to care about the device's native rate.
"""

from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np

SAMPLE_RATE = 16_000
"""Samples per second. What the speech recognisers expect."""

FRAME_MS = 20
"""Frame duration. Short enough for responsive endpointing, long enough that a
VAD has something to look at."""

SAMPLES_PER_FRAME = SAMPLE_RATE * FRAME_MS // 1000

_INT16_FULL_SCALE = 32768.0


@dataclass(frozen=True, slots=True)
class AudioFrame:
    """One 20 ms block of mono PCM16 audio, with its position in the session."""

    samples: np.ndarray
    """``int16`` samples, ``SAMPLES_PER_FRAME`` of them."""

    at_ms: int
    """Start of the frame, measured from the beginning of the session."""

    @property
    def rms(self) -> float:
        """Root mean square amplitude, normalised to ``[0.0, 1.0]``.

        Normalising here keeps every threshold in the system expressed in the
        same units regardless of the capture device's bit depth.
        """
        if self.samples.size == 0:
            return 0.0
        magnitude = np.sqrt(np.mean(np.square(self.samples.astype(np.float64))))
        return float(magnitude / _INT16_FULL_SCALE)


def iter_frames(pcm: bytes, *, start_ms: int = 0) -> Iterator[AudioFrame]:
    """Split raw PCM16 into whole frames.

    A trailing partial frame is dropped: padding it with silence would fabricate
    a pause that the candidate never took, which is exactly the kind of artefact
    the endpointing policy is sensitive to.

    Args:
        pcm: little-endian signed 16-bit mono samples.
        start_ms: session time of the first sample.

    Yields:
        Consecutive frames of ``FRAME_MS`` each.
    """
    samples = np.frombuffer(pcm, dtype="<i2")
    frame_count = samples.size // SAMPLES_PER_FRAME
    for index in range(frame_count):
        offset = index * SAMPLES_PER_FRAME
        yield AudioFrame(
            samples=samples[offset : offset + SAMPLES_PER_FRAME],
            at_ms=start_ms + index * FRAME_MS,
        )
