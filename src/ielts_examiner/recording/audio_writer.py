"""Streaming WAV output.

Audio is written as it arrives rather than buffered to the end of the exam, for
the same reason the event log flushes every append: a session that dies halfway
through should still leave behind everything it captured.
"""

import wave
from pathlib import Path
from types import TracebackType
from typing import Self

from ielts_examiner.audio.frames import SAMPLE_RATE

_CHANNELS = 1
_SAMPLE_WIDTH = 2


class WavWriter:
    """Appends PCM16 to a WAV file, keeping the header correct on close."""

    def __init__(self, path: Path, *, sample_rate: int = SAMPLE_RATE) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Not a context manager on purpose: the file stays open for the whole
        # exam so audio can be flushed as it arrives rather than at the end.
        self._file = wave.open(str(path), "wb")  # noqa: SIM115
        self._file.setnchannels(_CHANNELS)
        self._file.setsampwidth(_SAMPLE_WIDTH)
        self._file.setframerate(sample_rate)
        self._bytes_written = 0

    @property
    def duration_ms(self) -> int:
        """Audio written so far."""
        return self._bytes_written * 1000 // (SAMPLE_RATE * _SAMPLE_WIDTH)

    def write(self, pcm: bytes) -> None:
        """Append raw little-endian PCM16."""
        self._file.writeframes(pcm)
        self._bytes_written += len(pcm)

    def close(self) -> None:
        """Finalise the file."""
        self._file.close()

    def __enter__(self) -> Self:
        """Enter the context, returning the open writer."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Finalise the file, whether or not the session ended cleanly."""
        self.close()
